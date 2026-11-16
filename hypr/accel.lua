-- Pointer acceleration for the Keychron M6, set from the keychron-m6.panel
-- bar widget.
--
-- Load it from ~/.config/hypr/input.lua:
--
--   dofile(os.getenv("HOME") .. "/.config/omarchy/plugins/keychron-m6.panel/hypr/accel.lua")
--
-- The widget stores its choice as plain data under
-- ~/.local/state/keychron-m6/, never as Lua: device names come from USB and
-- Bluetooth descriptors and must not be executed. Both files are validated
-- here before they reach hl.device().

local home = os.getenv("HOME") or ""
local dir = home .. "/.local/state/keychron-m6/"

local function read_lines(path, limit)
  local file = io.open(path, "r")
  if not file then
    return {}
  end
  local lines = {}
  for line in file:lines() do
    if #lines >= limit then
      break
    end
    lines[#lines + 1] = line
  end
  file:close()
  return lines
end

local profile = read_lines(dir .. "accel-profile", 1)[1]
if profile ~= "flat" and profile ~= "adaptive" then
  return
end

local names = read_lines(dir .. "device-names", 32)
if #names == 0 then
  names = { "keychron-keychron-m6", "keychron--keychron-link-km" }
end

for _, name in ipairs(names) do
  if #name <= 128 and name:match("^[%l%d][%l%d:%._%-]*$") then
    hl.device({ name = name, accel_profile = profile })
  end
end
