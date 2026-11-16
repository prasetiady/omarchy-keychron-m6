-- Pointer acceleration and scroll speed for the Keychron M6, set from the
-- keychron-m6.panel bar widget.
--
-- Load it from ~/.config/hypr/input.lua:
--
--   dofile(os.getenv("HOME") .. "/.config/omarchy/plugins/keychron-m6.panel/hypr/pointer.lua")
--
-- The widget stores each choice as plain data under
-- ~/.local/state/keychron-m6/, never as Lua: device names come from USB and
-- Bluetooth descriptors and must not be executed. Every value is validated
-- here before it reaches hl.device().

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
  profile = nil
end

local factor = tonumber((read_lines(dir .. "scroll-factor", 1)[1] or ""):match("^%d+%.?%d*$") or "")
if factor and (factor < 0.1 or factor > 3) then
  factor = nil
end

if not profile and not factor then
  return
end

local names = read_lines(dir .. "device-names", 32)
if #names == 0 then
  names = { "keychron-keychron-m6", "keychron--keychron-link-km" }
end

-- Hyprland adds a number to a device name when the device reconnects
-- ("keychron--keychron-link-km-1"), and the number can change after a reboot
-- or a re-plug. Cover the base name and its numbered variants, so the settings
-- apply at startup without waiting for the panel to see the new name.
local seen = {}
local function apply(name)
  if seen[name] then
    return
  end
  seen[name] = true
  hl.device({ name = name, accel_profile = profile, scroll_factor = factor })
end

for _, name in ipairs(names) do
  if #name <= 128 and name:match("^[%l%d][%l%d:%._%-]*$") then
    local base = name:gsub("%-%d+$", "")
    apply(base)
    for n = 1, 9 do
      apply(base .. "-" .. n)
    end
  end
end
