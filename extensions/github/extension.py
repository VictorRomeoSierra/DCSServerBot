import asyncio
import git
import os
import re
import subprocess

from core import Extension, utils, Server, get_translation
from typing_extensions import override
from urllib.parse import urlparse


# Semver-only tag filter for the rollback command. Bare X.Y.Z per
# .github/release-tagging-spec.md in the XSAF repo. Non-version tags
# (backup/*, vrs-launch-*, etc.) live in a separate namespace and are
# intentionally excluded from rollback targets.
_SEMVER_TAG_RE = re.compile(r'^\d+\.\d+\.\d+$')

_ = get_translation(__name__.split('.')[1])


class GitHub(Extension):

    CONFIG_DICT = {
        "repo": {
            "type": str,
            "label": _("Repository"),
            "required": True
        },
        "branch": {
            "type": str,
            "label": _("Branch"),
            "default": "main",
            "required": True
        },
        "target": {
            "type": str,
            "label": _("Target"),
            "default": "{server.instance.home}\\Missions",
            "required": True
        },
        "filter": {
            "type": str,
            "label": _("Filter"),
            "required": False
        },
        "manifest": {
            "type": str,
            "label": _("Manifest"),
            "required": False
        }
    }

    def __init__(self, server: Server, config: dict):
        super().__init__(server, config)
        self.repo = self.config['repo']
        self.target = os.path.join(utils.format_string(self.config['target'], server=self.server,
                                                       instance=self.server.instance, node=self.node),
                                   self.get_repo_name(self.repo))

    @staticmethod
    def get_repo_name(repo: str) -> str:
        parsed_url = urlparse(repo)
        repo_name = os.path.basename(parsed_url.path)
        if repo_name.endswith('.git'):
            repo_name = repo_name[:-4]
        return repo_name

    @staticmethod
    def get_default_branch(target: str) -> str:
        result = subprocess.run(
            ['git', 'remote', 'show', 'origin'],
            cwd=target,
            capture_output=True,
            text=True,
            check=True
        )
        for line in result.stdout.splitlines():
            if "HEAD branch" in line:
                _, branch = line.split(": ")
                return branch.strip()
        return "master"

    def clone_with_filter(self, pattern: str):
        subprocess.run(['git', 'init'], cwd=self.target, check=True, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL)
        subprocess.run(['git', 'remote', 'add', '-f', 'origin', self.repo], cwd=self.target, check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(['git', 'config', 'core.sparseCheckout', 'true'], cwd=self.target, check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        sparse_checkout_path = os.path.join(self.target, '.git', 'info', 'sparse-checkout')
        with open(sparse_checkout_path, 'w') as f:
            f.write(pattern + '\n')

        branch = self.config.get('branch', self.get_default_branch(self.target))
        subprocess.run(['git', 'pull', '--set-upstream', 'origin', branch],
                       cwd=self.target, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    async def update(self):
        self.log.debug(f"{self.name}: Updating repository {self.repo} into {self.target}")
        repo = git.Repo(self.target)
        branch = self.config.get('branch') or self.get_default_branch(self.target)

        # Fetch first so we can inspect the remote without touching the
        # working tree.
        origin = repo.remotes.origin
        await asyncio.to_thread(origin.fetch)

        # Resolve local + remote HEAD commits. If anything goes sideways
        # (no remote-tracking ref yet, detached HEAD, etc.), fall back to
        # the legacy pull behavior so we don't regress an already-working
        # setup.
        try:
            local_commit = repo.head.commit
            remote_commit = repo.refs[f'origin/{branch}'].commit
        except (IndexError, KeyError, AttributeError, ValueError) as e:
            self.log.warning(
                f"{self.name}: could not resolve refs for rewind check "
                f"({e}); falling back to pull")
            await asyncio.to_thread(repo.git.pull)
            self._write_manifest(repo)
            return

        if local_commit.hexsha == remote_commit.hexsha:
            # Already in sync. Nothing to do; rewrite the manifest in case
            # it drifted on disk.
            self._write_manifest(repo)
            return

        # Rewind detection: the remote head is an ancestor of the local
        # head AND they differ. That means `origin/<branch>` moved
        # BACKWARDS relative to where we are. The legacy `repo.git.pull()`
        # path silently no-ops on this (FF-only) which caused the
        # 2026-05-25 Prod incident -- restarts kept loading hotfix-era
        # code because `git pull` couldn't rewind. See
        # postmortem-2026-05-25-prod-multi-lag-cascade.md.
        try:
            rewound = await asyncio.to_thread(
                repo.is_ancestor, remote_commit, local_commit)
        except git.GitCommandError as e:
            self.log.warning(
                f"{self.name}: rewind ancestor check failed ({e}); "
                f"falling back to pull")
            await asyncio.to_thread(repo.git.pull)
            self._write_manifest(repo)
            return

        if rewound:
            self.log.warning(
                f"{self.name}: origin/{branch} was rewound "
                f"(local={local_commit.hexsha[:8]} -> "
                f"remote={remote_commit.hexsha[:8]}); resetting hard. "
                f"Force-pushes propagate within one update cycle by design.")
            await asyncio.to_thread(
                repo.git.reset, '--hard', f'origin/{branch}')
        else:
            # Normal forward motion -- regular pull.
            await asyncio.to_thread(repo.git.pull)

        self._write_manifest(repo)

    async def reset_to_ref(self, ref: str) -> tuple[str, str]:
        """Reset the target repo to a given ref (tag, branch, or SHA).

        Used by the /vrs rollback admin command (plugins/vrs/commands.py).
        The ref is passed straight to `git reset --hard`, so callers
        should pass `refs/tags/X.Y.Z` to disambiguate from branches.

        Returns (old_sha, new_sha) for audit logging. Fetches tags first
        so freshly-pushed tags resolve.
        """
        self.log.info(f"{self.name}: reset {self.target} -> {ref}")
        repo = git.Repo(self.target)
        old_sha = repo.head.commit.hexsha
        await asyncio.to_thread(repo.remotes.origin.fetch, tags=True)
        await asyncio.to_thread(repo.git.reset, '--hard', ref)
        new_sha = repo.head.commit.hexsha
        self._write_manifest(repo)
        return old_sha, new_sha

    async def list_release_tags(self) -> list[str]:
        """Return semver-style release tags sorted descending (newest first).

        Filters to bare X.Y.Z (per the XSAF release-tagging spec) so the
        rollback autocomplete doesn't surface backup/save-point tags.
        Fetches tags first so the list reflects the published state, not
        the last cached snapshot.
        """
        repo = git.Repo(self.target)
        await asyncio.to_thread(repo.remotes.origin.fetch, tags=True)
        tags = [t.name for t in repo.tags if _SEMVER_TAG_RE.match(t.name)]

        def _version_key(name: str) -> tuple[int, int, int]:
            return tuple(int(p) for p in name.split('.'))  # type: ignore[return-value]

        return sorted(tags, key=_version_key, reverse=True)

    def _write_manifest(self, repo):
        manifest = self.config.get('manifest')
        if not manifest:
            return
        try:
            log_output = repo.git.log('-3', '--format=%H|%an|%s')
            manifest_path = os.path.join(self.target, manifest)
            tmp_path = manifest_path + '.tmp'
            with open(tmp_path, 'w', encoding='utf-8') as f:
                f.write(log_output)
                if log_output and not log_output.endswith('\n'):
                    f.write('\n')
            os.replace(tmp_path, manifest_path)
            self.log.debug(f"{self.name}: wrote recent-commits manifest to {manifest_path}")
        except Exception as e:
            self.log.warning(f"{self.name}: failed to write recent-commits manifest: {e}")

    async def clone(self):
        self.log.debug(f"{self.name}: Cloning repository {self.repo} into {self.target}")
        if not os.path.exists(self.target):
            os.makedirs(self.target)

        pattern = self.config.get('filter')
        if filter:
            await asyncio.to_thread(self.clone_with_filter, pattern)
        else:
            git.Repo.clone_from(self.repo, self.target)

    @override
    async def beforeMissionLoad(self, filename: str) -> tuple[str, bool]:
        try:
            await self.update()
        except (git.NoSuchPathError, git.InvalidGitRepositoryError):
            await self.clone()
        return filename, False

    @override
    async def startup(self, *, quiet: bool = False) -> bool:
        return await super().startup(quiet=True)

    @override
    def shutdown(self, *, quiet: bool = False) -> bool:
        return super().shutdown(quiet=True)
