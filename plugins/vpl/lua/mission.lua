local base		= _G
dcsbot 			= base.dcsbot

--[[
    Initialize the VPL Events handlers.
]]--

function dcsbot.vplSavePersistentObject(coords, name, freq, objectType)
	log.write('DCSServerBot', log.DEBUG, 'VPL: vplSavePersistentObject() (mission.lua)')
	local msg = {}
	msg.command = 'vplSavePersistentObject'
  -- local json = net.lua2json(data)
	msg.name = name
  msg.coords = coords
  msg.freq = freq
  msg.objectType = objectType
	dcsbot.sendBotTable(msg)
end

function dcsbot._vplSendPersistentObjects(json)
	log.write('DCSServerBot', log.DEBUG, 'VPL: _vplSendPersistentObjects() (mission.lua)')
	local lua = net.json2lua(json)
	vpl.spawnPersistentObject(lua)
end

function dcsbot.vplGetPersistentObjects(data)
	log.write('DCSServerBot', log.DEBUG, 'VPL: vplGetPersistentObjects() (mission.lua)')
	local msg = {}
	msg.command = 'vplGetPersistentObjects'
  local json = net.lua2json(data)
	msg.data = json
	dcsbot.sendBotTable(msg)
end

env.info("DCSServerBot - VPL: mission.lua loaded.")