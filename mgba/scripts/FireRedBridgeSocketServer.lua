-- ***********************
-- FireRed Bridge Socket Server
-- Custom Lua interface for fast memory reads + input control
-- ***********************

-- logLevel values
-- 1 = Debug
-- 2 = Information
-- 3 = Warning
-- 4 = Error
-- 5 = None
local logLevel = 4
local truncateLogs = true
local TERMINATION_MARKER <const> = "<|END|>"
local DEFAULT_RETURN <const> = "<|SUCCESS|>";
local ERROR_RETURN <const> = "<|ERROR|>";

-- ***********************
-- Sockets
-- ***********************

local server = nil
local socketList = {}
local nextID = 1
local port = 8888

function beginSocket()
	while not server do
		server, error = socket.bind(nil, port)
		if error then
			if error == socket.ERRORS.ADDRESS_IN_USE then
				port = port + 1
			else
				logError(formatSocketMessage("Bind", error, true))
				break
			end
		else
			local ok
			ok, error = server:listen()
			if error then
				server:close()
				logError(formatSocketMessage("Listen", error, true))
			else
				logWithOverride("FireRed bridge socket server ready. Listening on port " .. port, 4)
				server:add("received", socketAccept)
			end
		end
	end
end

function socketAccept()
	local sock, error = server:accept()
	if error then
		logError(formatSocketMessage("Accept", error, true))
		return
	end
	local id = nextID
	nextID = id + 1
	socketList[id] = sock
	sock:add("received", function() socketReceived(id) end)
	sock:add("error", function() socketError(id) end)
	logDebug(formatSocketMessage(id, "Connected"))
end

function socketReceived(id)
	local sock = socketList[id]
	if not sock then return end
	sock._buffer = sock._buffer or ""
	while true do
		local chunk, error = sock:receive(1024)
		if chunk then
			sock._buffer = sock._buffer .. chunk
			while true do
				local marker_start, marker_end = sock._buffer:find(TERMINATION_MARKER, 1, true)
				if not marker_start then break end
				local message = sock._buffer:sub(1, marker_start - 1)
				sock._buffer = sock._buffer:sub(marker_end + 1)
				logDebug(formatSocketMessage(id, message:match("^(.-)%s*$")))

				local success, returnValue = pcall(function()
					return messageRouter(message:match("^(.-)%s*$"))
				end)

				if not success then
					logError("Error executing command: " .. tostring(returnValue))
					sock:send(ERROR_RETURN .. TERMINATION_MARKER)
				else
					sock:send(returnValue .. TERMINATION_MARKER)
				end
			end
		elseif error then
			-- socket.ERRORS.AGAIN is expected for non-blocking reads
			if error ~= socket.ERRORS.AGAIN then
				if error == "disconnected" then
					logDebug(formatSocketMessage(id, error, false))
				elseif error == socket.ERRORS.UNKNOWN_ERROR then
					logDebug(formatSocketMessage(id, "disconnected*", false))
				else
					logError(formatSocketMessage(id, error, true))
				end
				socketStop(id)
			end
			return
		end
	end
end

function socketStop(id)
	local sock = socketList[id]
	socketList[id] = nil
	sock:close()
end

function socketError(id, error)
	logError(formatSocketMessage(id, error, true))
	socketStop(id)
end

function formatSocketMessage(id, msg, isError)
	local prefix = "Socket " .. id
	if isError then
		prefix = prefix .. " Error: "
	else
		prefix = prefix .. " Received: "
	end
	return prefix .. (msg and tostring(msg) or "Probably exceeding limit")
end

-- ***********************
-- Message Router
-- ***********************

local keyValues = {
	["A"] = 0,
	["B"] = 1,
	["Select"] = 2,
	["Start"] = 3,
	["Right"] = 4,
	["Left"] = 5,
	["Up"] = 6,
	["Down"] = 7,
	["R"] = 8,
	["L"] = 9
}

function messageRouter(rawMessage)
	local messageType, rest = rawMessage:match("^([^,]+),(.*)$")

	local messageValue1, messageValue2, messageValue3

	-- Changes behaviour if the second argument is an array
	if rest and rest:sub(1,1) == "[" then
		-- Find matching closing bracket
		local bracketCount = 1
		local endBracket
		for i = 2, #rest do
			if rest:sub(i,i) == "[" then
				bracketCount = bracketCount + 1
			elseif rest:sub(i,i) == "]" then
				bracketCount = bracketCount - 1
				if bracketCount == 0 then
					endBracket = i
					break
				end
			end
		end

		if endBracket then
			messageValue1 = rest:sub(1, endBracket)
			-- Parse remaining values after the bracketed content
			local remaining = rest:sub(endBracket + 2) -- +2 to skip the comma after closing bracket
			if remaining ~= "" then
				local remainingValues = splitStringToTable(remaining, ",")
				messageValue2 = remainingValues[1]
				messageValue3 = remainingValues[2]
			end
		end
	else
		-- Original comma-based parsing for non-bracketed content
		local parsedInput = splitStringToTable(rawMessage, ",")
		messageType = parsedInput[1]
		messageValue1 = parsedInput[2]
		messageValue2 = parsedInput[3]
		messageValue3 = parsedInput[4]
	end

	local returnValue = DEFAULT_RETURN

	logInformation("messageRouter:\n\tRaw message: " .. rawMessage .. "\n\tmessageType: " .. (messageType or "") .. "\n\tmessageValue1: " .. (messageValue1 or "") .. "\n\tmessageValue2: " .. (messageValue2 or "") .. "\n\tmessageValue3: " .. (messageValue3 or ""))

	if rawMessage == "<|ACK|>" then
		logInformation("Connecting.")
	elseif messageType == "bridge.ping" then
		returnValue = "pong"
	elseif messageType == "bridge.read8" then
		returnValue = emu:read8(parseNumber(messageValue1))
	elseif messageType == "bridge.read16" then
		returnValue = emu:read16(parseNumber(messageValue1))
	elseif messageType == "bridge.read32" then
		returnValue = emu:read32(parseNumber(messageValue1))
	elseif messageType == "bridge.readRange" then
		returnValue = convertBinaryToByteString(emu:readRange(parseNumber(messageValue1), parseNumber(messageValue2)))
	elseif messageType == "bridge.readRangeHex" then
		returnValue = convertBinaryToHexString(emu:readRange(parseNumber(messageValue1), parseNumber(messageValue2)))
	elseif messageType == "bridge.readRanges" then
		returnValue = readRanges(messageValue1)
	elseif messageType == "bridge.readRangesHex" then
		returnValue = readRangesHex(messageValue1)
	elseif messageType == "bridge.screenshot" then
		-- Capture a PNG screenshot of the current emulator framebuffer.
		-- `messageValue1` should be a file path (recommended: absolute path).
		-- Note: mGBA Lua API: emu:screenshot(filename)
		emu:screenshot(messageValue1)
		returnValue = DEFAULT_RETURN
	elseif messageType == "bridge.saveStateFile" then
		-- Save a savestate file to disk.
		-- `messageValue1` should be a file path (recommended: absolute path).
		-- Note: mGBA Lua API: emu:saveStateFile(filename)
		local ok = emu:saveStateFile(messageValue1)
		if ok then
			returnValue = "true"
		else
			returnValue = "false"
		end
	elseif messageType == "bridge.reset" then
		-- Soft reset the core back to the boot/title screen.
		-- Note: mGBA Lua API: emu:reset()
		emu:reset()
		returnValue = DEFAULT_RETURN
	elseif messageType == "bridge.pressButtons" then
		manageButtons(messageValue1, tonumber(messageValue2))
	elseif messageType == "bridge.holdButton" then
		manageButton(messageValue1, tonumber(messageValue2))
	elseif messageType == "bridge.controlInit" then
		returnValue = controlInit(messageValue1)
	elseif messageType == "bridge.control" then
		returnValue = controlEnqueue(messageValue1)
	elseif messageType == "bridge.controlStatus" then
		returnValue = controlStatus()
	elseif (rawMessage ~= nil or rawMessage ~= '') then
		logInformation("Unable to route raw message: " .. rawMessage)
	else
		logInformation(messageType)
	end

	returnValue = tostring(returnValue or DEFAULT_RETURN)

	logInformation("Returning: " .. returnValue)
	return returnValue
end

-- ***********************
-- Button (Convenience abstraction)
-- ***********************

function addButton(keyLetter)
	local key = keyValues[keyLetter]
	emu:addKey(key)
end

function clearButton(keyLetter)
	local key = keyValues[keyLetter]
	emu:clearKey(key)
end

function addButtons(keyLetters)
	local keyLettersArray = splitStringToTable(keyLetters, ";")
	local keys = {}
	for i, keyLetter in ipairs(keyLettersArray) do
		keys[i] = keyValues[keyLetter]
	end
	local bitmask = toBitmask(keys)
	emu:addKeys(bitmask)
end

function clearButtons(keyLetters)
	local keyLettersArray = splitStringToTable(keyLetters, ";")
	local keys = {}
	for i, keyLetter in ipairs(keyLettersArray) do
		keys[i] = keyValues[keyLetter]
	end
	local bitmask = toBitmask(keys)
	emu:clearKeys(bitmask)
end

local keyEventQueue = {}

function manageButton(keyLetter, duration)
	duration = duration or 15
	local key = keyValues[keyLetter]
	local bitmask = toBitmask({key})
	enqueueButtons(bitmask, duration)
end

function manageButtons(keyLetters, duration)
	duration = duration or 15
	local keyLettersArray = splitStringToTable(keyLetters, ";")
	local keys = {}
	for i, keyLetter in ipairs(keyLettersArray) do
		keys[i] = keyValues[keyLetter]
	end
	local bitmask = toBitmask(keys)
	enqueueButtons(bitmask, duration)
end

function enqueueButtons(keyMask, duration)
	local startFrame = emu:currentFrame()
	local endFrame = startFrame + duration + 1

	table.insert(keyEventQueue,
	{
		keyMask = keyMask,
		startFrame = startFrame,
		endFrame = endFrame,
		pressed = false
	})
end

function updateKeys()
	local indexesToRemove = {}

	for index, keyEvent in ipairs(keyEventQueue) do
		if emu:currentFrame() >= keyEvent.startFrame and emu:currentFrame() <= keyEvent.endFrame and not keyEvent.pressed then
			emu:addKeys(keyEvent.keyMask)
			keyEvent.pressed = true
		elseif emu:currentFrame() > keyEvent.endFrame then
			emu:clearKeys(keyEvent.keyMask)
			table.insert(indexesToRemove, index)
		end
	end

	for _, i in ipairs(indexesToRemove) do
		table.remove(keyEventQueue, i)
	end
end

callbacks:add("frame", updateKeys)

-- ***********************
-- Overworld Control (Smart movement / facing)
-- ***********************

local CONTROL_QUEUE_MAX <const> = 64

local GMAIN_CALLBACK2_OFFSET <const> = 0x04
local GMAIN_IN_BATTLE_OFFSET <const> = 0x439

local PLAYER_AVATAR_RUNNING_STATE_OFFSET <const> = 0x02
local PLAYER_AVATAR_TILE_TRANSITION_STATE_OFFSET <const> = 0x03
local PLAYER_AVATAR_OBJECT_EVENT_ID_OFFSET <const> = 0x05
local PLAYER_AVATAR_PREVENT_STEP_OFFSET <const> = 0x06

local OBJECT_EVENT_SIZE <const> = 0x24
local OBJECT_EVENT_FLAGS0_OFFSET <const> = 0x00
local OBJECT_EVENT_CURRENT_X_OFFSET <const> = 0x10
local OBJECT_EVENT_CURRENT_Y_OFFSET <const> = 0x12
local OBJECT_EVENT_FACING_DIR_OFFSET <const> = 0x18
local OBJECT_EVENT_MOVEMENT_ACTION_ID_OFFSET <const> = 0x1C

local MOVEMENT_ACTION_NONE <const> = 0xFF

local PLAYER_RUNNING_STATE_NOT_MOVING <const> = 0
local PLAYER_RUNNING_STATE_TURN_DIRECTION <const> = 1
local PLAYER_RUNNING_STATE_MOVING <const> = 2

local TILE_TRANSITION_NOT_MOVING <const> = 0
local TILE_TRANSITION_IN_PROGRESS <const> = 1
local TILE_TRANSITION_TILE_CENTER <const> = 2

local IN_BATTLE_BITMASK <const> = 0x02

local CONTROL_TAP_FRAMES <const> = 2
local CONTROL_FACE_TAP_FRAMES <const> = 1
local CONTROL_MOVE_WAIT_START_TIMEOUT <const> = 90
local CONTROL_MOVE_WAIT_END_TIMEOUT <const> = 90
local CONTROL_FACE_TIMEOUT <const> = 30

local controlState = {
	initialized = false,
	gPlayerAvatar = 0,
	gObjectEvents = 0,
	gMain = 0,
	cb2Overworld = 0,
	sLockFieldControls = 0,
	queue = {},
	active = nil
}

local function normalizeCommand(command)
	if not command then
		return ""
	end
	command = tostring(command)
	command = command:match("^%s*(.-)%s*$")
	command = command:lower()
	command = command:gsub("-", "_")
	return command
end

local function keyLetterForTapCommand(command)
	if command == "a" then return "A" end
	if command == "b" then return "B" end
	if command == "start" then return "Start" end
	if command == "select" then return "Select" end
	if command == "l" then return "L" end
	if command == "r" then return "R" end
	if command == "up" then return "Up" end
	if command == "down" then return "Down" end
	if command == "left" then return "Left" end
	if command == "right" then return "Right" end
	return nil
end

local function directionKeyLetterForFaceCommand(command)
	if command == "face_up" then return "Up" end
	if command == "face_down" then return "Down" end
	if command == "face_left" then return "Left" end
	if command == "face_right" then return "Right" end
	return nil
end

local function desiredFacingForKeyLetter(keyLetter)
	-- See gObjectEvents.facingDirection in decomp include/global.fieldmap.h (DIR_* values)
	if keyLetter == "Down" then return 1 end
	if keyLetter == "Up" then return 2 end
	if keyLetter == "Left" then return 3 end
	if keyLetter == "Right" then return 4 end
	return 0
end

local function canUseOverworldControl()
	if not controlState.initialized then
		return false
	end
	if not controlState.gPlayerAvatar or controlState.gPlayerAvatar == 0 then return false end
	if not controlState.gObjectEvents or controlState.gObjectEvents == 0 then return false end
	if not controlState.gMain or controlState.gMain == 0 then return false end
	if not controlState.cb2Overworld or controlState.cb2Overworld == 0 then return false end
	if not controlState.sLockFieldControls or controlState.sLockFieldControls == 0 then return false end

	local cb2 = emu:read32(controlState.gMain + GMAIN_CALLBACK2_OFFSET)
	-- Function pointers are Thumb (bit0=1) in RAM; symbols are even addresses.
	if (cb2 & 0xFFFFFFFE) ~= (controlState.cb2Overworld & 0xFFFFFFFE) then
		return false
	end

	if emu:read8(controlState.sLockFieldControls) ~= 0 then
		return false
	end

	local inBattleAddr = controlState.gMain + GMAIN_IN_BATTLE_OFFSET
	local inBattle = (emu:read8(inBattleAddr) & IN_BATTLE_BITMASK) ~= 0
	if inBattle then
		return false
	end

	local preventStep = emu:read8(controlState.gPlayerAvatar + PLAYER_AVATAR_PREVENT_STEP_OFFSET)
	if preventStep ~= 0 then
		return false
	end

	return true
end

local function readPlayerAvatarSnapshot()
	local base = controlState.gPlayerAvatar
	return {
		runningState = emu:read8(base + PLAYER_AVATAR_RUNNING_STATE_OFFSET),
		tileTransitionState = emu:read8(base + PLAYER_AVATAR_TILE_TRANSITION_STATE_OFFSET),
		objectEventId = emu:read8(base + PLAYER_AVATAR_OBJECT_EVENT_ID_OFFSET)
	}
end

	local function readPlayerObjectEventSnapshot(objectEventId)
		local base = controlState.gObjectEvents + (objectEventId * OBJECT_EVENT_SIZE)
		local flags0 = emu:read8(base + OBJECT_EVENT_FLAGS0_OFFSET)
		-- Low byte contains facing + movement direction (nibbles). We only need facing (DIR_*).
		local facingBits = emu:read8(base + OBJECT_EVENT_FACING_DIR_OFFSET)
		local movementActionId = emu:read8(base + OBJECT_EVENT_MOVEMENT_ACTION_ID_OFFSET)
		local heldMovementActive = (flags0 & 0x40) ~= 0
		local heldMovementFinished = (flags0 & 0x80) ~= 0
		local singleMovementActive = (flags0 & 0x02) ~= 0
		return {
			x = emu:read16(base + OBJECT_EVENT_CURRENT_X_OFFSET),
			y = emu:read16(base + OBJECT_EVENT_CURRENT_Y_OFFSET),
			facing = (facingBits & 0x07),
			flags0 = flags0,
			movementActionId = movementActionId,
			singleMovementActive = singleMovementActive,
			heldMovementActive = heldMovementActive,
			heldMovementFinished = heldMovementFinished,
			-- Mirror pokefirered's ObjectEventIsHeldMovementActive() semantics:
			-- "active" only matters when the actionId != NONE, and we don't want to block on finished=1.
			heldMovementBusy = heldMovementActive and (movementActionId ~= MOVEMENT_ACTION_NONE) and (not heldMovementFinished)
		}
	end

local function overwriteActiveControl(nilReason)
	if controlState.active and controlState.active.heldKeyLetter then
		clearButton(controlState.active.heldKeyLetter)
	end
	controlState.active = nil
end

function controlInit(bracketedAddrs)
	local values = parseNumberList(bracketedAddrs)
	if #values < 5 then
		return ERROR_RETURN .. "controlInit expects [gPlayerAvatar,gObjectEvents,gMain,CB2_Overworld,sLockFieldControls]"
	end

	controlState.gPlayerAvatar = values[1] or 0
	controlState.gObjectEvents = values[2] or 0
	controlState.gMain = values[3] or 0
	controlState.cb2Overworld = values[4] or 0
	controlState.sLockFieldControls = values[5] or 0
	controlState.initialized = true
	controlState.queue = {}
	overwriteActiveControl("reinit")

	return "controlInit.ok"
end

function controlEnqueue(command)
	local normalized = normalizeCommand(command)

	if not normalized or normalized == "" then
		return ERROR_RETURN .. "control requires a command"
	end

	if #controlState.queue >= CONTROL_QUEUE_MAX then
		return ERROR_RETURN .. "control queue full"
	end

	local keyLetter = keyLetterForTapCommand(normalized)
	local faceKeyLetter = directionKeyLetterForFaceCommand(normalized)

	if faceKeyLetter then
		table.insert(controlState.queue, {
			kind = "face",
			keyLetter = faceKeyLetter,
			state = "start",
			deadlineFrame = 0,
			heldKeyLetter = nil
		})
		return "control.ok"
	end

	if normalized == "up" or normalized == "down" or normalized == "left" or normalized == "right" then
		table.insert(controlState.queue, {
			kind = "move",
			keyLetter = keyLetter,
			state = "start",
			deadlineFrame = 0,
			heldKeyLetter = nil,
			afterStartTileTransitionSeen = false
		})
		return "control.ok"
	end

	if keyLetter then
		-- Tap inputs (A/B/Start/Select/L/R + D-pad fallback when not in overworld)
		manageButton(keyLetter, CONTROL_TAP_FRAMES)
		return "control.ok"
	end

	return ERROR_RETURN .. "unknown control command: " .. normalized
end

local function updateControlMove(control)
	local nowFrame = emu:currentFrame()

	if control.state == "start" then
		control.state = "wait_ready"
		control.deadlineFrame = nowFrame + CONTROL_MOVE_WAIT_START_TIMEOUT + CONTROL_MOVE_WAIT_END_TIMEOUT
	end

		if control.state == "wait_ready" then
			if not canUseOverworldControl() then
				-- Not in overworld / controls locked: degrade to a short tap so that D-pad still works in menus.
				manageButton(control.keyLetter, CONTROL_TAP_FRAMES)
				return true
		end

			local avatar = readPlayerAvatarSnapshot()
			local obj = readPlayerObjectEventSnapshot(avatar.objectEventId)

			-- Wait for a safe input window to start holding direction.
			if avatar.tileTransitionState == TILE_TRANSITION_IN_PROGRESS or obj.singleMovementActive or obj.heldMovementBusy then
				if nowFrame >= (control.deadlineFrame or 0) then
					return true
				end
				return false
			end

			addButton(control.keyLetter)
			control.heldKeyLetter = control.keyLetter
		control.state = "wait_start"
		control.deadlineFrame = nowFrame + CONTROL_MOVE_WAIT_START_TIMEOUT
		return false
	end

	if control.state == "wait_start" then
		if not canUseOverworldControl() then
			-- Controls got locked mid-command; release and finish.
			if control.heldKeyLetter then
				clearButton(control.heldKeyLetter)
				control.heldKeyLetter = nil
			end
			return true
		end

		local avatar = readPlayerAvatarSnapshot()

		if avatar.tileTransitionState == TILE_TRANSITION_IN_PROGRESS then
			-- Movement started; release direction to avoid chaining into a second tile.
			if control.heldKeyLetter then
				clearButton(control.heldKeyLetter)
				control.heldKeyLetter = nil
			end
			control.state = "wait_end"
			control.deadlineFrame = nowFrame + CONTROL_MOVE_WAIT_END_TIMEOUT
			return false
		end

		if nowFrame >= (control.deadlineFrame or 0) then
			-- Failed to start (collision / blocked); release and finish.
			if control.heldKeyLetter then
				clearButton(control.heldKeyLetter)
				control.heldKeyLetter = nil
			end
			return true
		end

		return false
	end

	if control.state == "wait_end" then
		local avatar = readPlayerAvatarSnapshot()
		if avatar.tileTransitionState ~= TILE_TRANSITION_IN_PROGRESS then
			return true
		end
		if nowFrame >= (control.deadlineFrame or 0) then
			return true
		end
		return false
	end

	return true
end

local function updateControlFace(control)
	local nowFrame = emu:currentFrame()

	if control.state == "start" then
		control.state = "wait_ready"
		control.deadlineFrame = nowFrame + CONTROL_FACE_TIMEOUT
	end

		if control.state == "wait_ready" then
			if not canUseOverworldControl() then
				-- Not in overworld / controls locked: degrade to a short tap so it behaves like a normal dpad press in menus.
				manageButton(control.keyLetter, CONTROL_TAP_FRAMES)
				return true
		end

			local avatar = readPlayerAvatarSnapshot()
			local obj = readPlayerObjectEventSnapshot(avatar.objectEventId)

			if avatar.tileTransitionState == TILE_TRANSITION_IN_PROGRESS or obj.singleMovementActive or obj.heldMovementBusy then
				if nowFrame >= (control.deadlineFrame or 0) then
					return true
				end
				return false
			end

		local desiredFacing = desiredFacingForKeyLetter(control.keyLetter)
		if desiredFacing ~= 0 and obj.facing == desiredFacing then
			return true
		end

		-- Face-only must never step. Use a short tap to trigger TURN_DIRECTION,
		-- then release before the game can transition into MOVING.
			addButton(control.keyLetter)
			control.heldKeyLetter = control.keyLetter
			control.state = "release"
			control.deadlineFrame = nowFrame + CONTROL_FACE_TAP_FRAMES
			return false
		end

	if control.state == "release" then
		if nowFrame >= (control.deadlineFrame or 0) then
			if control.heldKeyLetter then
				clearButton(control.heldKeyLetter)
				control.heldKeyLetter = nil
			end
			return true
		end
		return false
	end

	return true
end

function controlStatus()
	local parts = {}

	table.insert(parts, "initialized=" .. tostring(controlState.initialized and 1 or 0))
	if not controlState.initialized then
		return table.concat(parts, ",")
	end

	local cb2 = 0
	local cb2Match = 0
	local lock = -1
	local inBattle = 0
	local preventStep = -1

	if controlState.gMain and controlState.gMain ~= 0 then
		cb2 = emu:read32(controlState.gMain + GMAIN_CALLBACK2_OFFSET)
		cb2Match = ((cb2 & 0xFFFFFFFE) == (controlState.cb2Overworld & 0xFFFFFFFE)) and 1 or 0
	end
	if controlState.sLockFieldControls and controlState.sLockFieldControls ~= 0 then
		lock = emu:read8(controlState.sLockFieldControls)
	end
	if controlState.gMain and controlState.gMain ~= 0 then
		local inBattleAddr = controlState.gMain + GMAIN_IN_BATTLE_OFFSET
		inBattle = ((emu:read8(inBattleAddr) & IN_BATTLE_BITMASK) ~= 0) and 1 or 0
	end
	if controlState.gPlayerAvatar and controlState.gPlayerAvatar ~= 0 then
		preventStep = emu:read8(controlState.gPlayerAvatar + PLAYER_AVATAR_PREVENT_STEP_OFFSET)
	end

	table.insert(parts, string.format("cb2=0x%08X", cb2))
	table.insert(parts, string.format("cb2Expected=0x%08X", controlState.cb2Overworld or 0))
	table.insert(parts, "cb2Match=" .. tostring(cb2Match))
	table.insert(parts, "lock=" .. tostring(lock))
	table.insert(parts, "inBattle=" .. tostring(inBattle))
	table.insert(parts, "preventStep=" .. tostring(preventStep))
	table.insert(parts, "canOverworld=" .. tostring(canUseOverworldControl() and 1 or 0))
	table.insert(parts, "queue=" .. tostring(#controlState.queue))
	table.insert(parts, "active=" .. tostring(controlState.active and (controlState.active.kind .. ":" .. (controlState.active.state or "")) or "none"))

		if canUseOverworldControl() then
			local avatar = readPlayerAvatarSnapshot()
			local obj = readPlayerObjectEventSnapshot(avatar.objectEventId)
			table.insert(parts, "runningState=" .. tostring(avatar.runningState))
			table.insert(parts, "tileTransitionState=" .. tostring(avatar.tileTransitionState))
			table.insert(parts, "objId=" .. tostring(avatar.objectEventId))
			table.insert(parts, "x=" .. tostring(obj.x))
			table.insert(parts, "y=" .. tostring(obj.y))
			table.insert(parts, "facing=" .. tostring(obj.facing))
			table.insert(parts, string.format("flags0=0x%02X", obj.flags0 or 0))
			table.insert(parts, string.format("movementActionId=0x%02X", obj.movementActionId or 0))
			table.insert(parts, "singleMovementActive=" .. tostring(obj.singleMovementActive and 1 or 0))
			table.insert(parts, "heldMovementActive=" .. tostring(obj.heldMovementActive and 1 or 0))
			table.insert(parts, "heldMovementFinished=" .. tostring(obj.heldMovementFinished and 1 or 0))
			table.insert(parts, "heldMovementBusy=" .. tostring(obj.heldMovementBusy and 1 or 0))
		end

		return table.concat(parts, ",")
	end

function updateControl()
	if not controlState.active then
		if #controlState.queue == 0 then
			return
		end
		controlState.active = table.remove(controlState.queue, 1)
	end

	local active = controlState.active
	local done = true

	if active.kind == "move" then
		done = updateControlMove(active)
	elseif active.kind == "face" then
		done = updateControlFace(active)
	else
		done = true
	end

	if done then
		if active.heldKeyLetter then
			clearButton(active.heldKeyLetter)
		end
		controlState.active = nil
	end
end

callbacks:add("frame", updateControl)

-- ***********************
-- Utility
-- ***********************

function splitStringToTable(inputstr, sep)
	if sep == nil then
		sep = "%s"
	end
	local t = {}
	for str in string.gmatch(inputstr, "([^"..sep.."]+)") do
		table.insert(t, str)
	end
	return t
end

function toBitmask(keys)
	local mask = 0
	for _, key in ipairs(keys) do
		mask = mask | (1 << tonumber(key))
	end
	return mask
end

function convertBinaryToByteString(binaryString)
	local bytes = {}
	for i = 1, #binaryString do
		table.insert(bytes, string.format("%02x", binaryString:byte(i)))
	end
	return table.concat(bytes, ",")
end

function convertBinaryToHexString(binaryString)
	local bytes = {}
	for i = 1, #binaryString do
		bytes[i] = string.format("%02x", binaryString:byte(i))
	end
	return table.concat(bytes)
end

function parseNumber(value)
	if not value then
		return nil
	end
	local num = tonumber(value)
	if not num then
		local lower = string.lower(value)
		if lower:sub(1, 2) == "0x" then
			num = tonumber(value:sub(3), 16)
		end
	end
	return num
end

function parseNumberList(bracketedBytes)
	if not bracketedBytes then
		return {}
	end
	local inner = bracketedBytes:match("%[(.*)%]")
	if not inner then
		return {}
	end
	local values = {}
	for token in inner:gmatch("([^,]+)") do
		local trimmed = token:match("^%s*(.-)%s*$")
		if trimmed ~= "" then
			local num = parseNumber(trimmed)
			if num then
				table.insert(values, num)
			end
		end
	end
	return values
end

function readRanges(bracketedRanges)
	local ranges = parseNumberList(bracketedRanges)
	local outputs = {}
	local i = 1
	while i <= #ranges do
		local addr = ranges[i]
		local len = ranges[i + 1] or 0
		if addr and len and len > 0 then
			local bytes = emu:readRange(addr, len)
			table.insert(outputs, convertBinaryToByteString(bytes))
		else
			table.insert(outputs, "")
		end
		i = i + 2
	end
	return table.concat(outputs, "|")
end

function readRangesHex(bracketedRanges)
	local ranges = parseNumberList(bracketedRanges)
	local outputs = {}
	local i = 1
	while i <= #ranges do
		local addr = ranges[i]
		local len = ranges[i + 1] or 0
		if addr and len and len > 0 then
			local bytes = emu:readRange(addr, len)
			table.insert(outputs, convertBinaryToHexString(bytes))
		else
			table.insert(outputs, "")
		end
		i = i + 2
	end
	return table.concat(outputs, "|")
end

-- ***********************
-- Logging
-- ***********************

function formatLogMessage(message)
	if truncateLogs and #message > 500 then
		return string.sub(message, 1, 97) .. "..."
	end
	return message
end

function logDebug(message)
	if logLevel <= 1 then
		local timestamp = "[" .. os.date("%X", os.time()) .. "] "
		console:log(timestamp .. formatLogMessage(message))
	end
end

function logInformation(message)
	if logLevel <= 2 then
		local timestamp = "[" .. os.date("%X", os.time()) .. "] "
		console:log(timestamp .. formatLogMessage(message))
	end
end

function logWarning(message)
	if logLevel <= 3 then
		local timestamp = "[" .. os.date("%X", os.time()) .. "] "
		console:warn(timestamp .. formatLogMessage(message))
	end
end

function logError(message)
	if logLevel <= 4 then
		local timestamp = "[" .. os.date("%X", os.time()) .. "] "
		console:error(timestamp .. formatLogMessage(message))
	end
end

function logWithOverride(message, overrideLogLevel)
	if logLevel <= overrideLogLevel then
		local timestamp = "[" .. os.date("%X", os.time()) .. "] "
		console:log(timestamp .. formatLogMessage(message))
	end
end

-- ***********************
-- Start
-- ***********************

beginSocket()
