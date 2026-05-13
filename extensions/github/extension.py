import asyncio
import git
import os
import subprocess

from core import Extension, utils, Server, get_translation
from typing_extensions import override
from urllib.parse import urlparse

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
        repo.git.pull()
        self._write_manifest(repo)

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
