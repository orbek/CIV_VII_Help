# Verified against the live game, turn 59, Rome, 2026-09-13

## Transport
- TCP 127.0.0.1:4318. Open only when `[Debug] EnableTuner 1` in AppOptions.txt.
- Framing: uint32 LE length (payload incl. NUL) | int32 LE tag | NUL-terminated UTF-8.
- TAG_HANDSHAKE=4: send "APP:<name>", then "LSQ:" -> returns app id and the
  NUL-separated list of Lua states as index,name pairs.
- TAG_COMMAND=3: "CMD:<state_index>:<lua>". Output arrives as tag-4 messages
  prefixed "O\0<StateName>: ". Large output splits across packets -> collect
  until a sentinel the caller printed.

## State indices are NOT stable
Observed this session: 4=GameCore_Tuner, 125=InGame, 2=AdvisorProbe (our mod),
111=AdvisorProbeUI (our mod). Loaded mods shift the numbering. Resolve by NAME
from the LSQ reply every connection. Hardcoding an index reads another VM.

## Two VMs, different capabilities. Three outcomes, not two.
A binding can be (a) absent, (b) present but raising "Not Implemented.",
(c) working. (b) is the trap: it looks like a live method and fails at call time.

### GameCore_Tuner -- WORKING
Treasury: GetTotalMaintenance=1, GetBuildingMaintenance=0,
  GetDistrictMaintenance=1, GetUnitMaintenance=0, GetGoldBalance=152, GetGoldYield=8
CityGrowth: GetAmenities=3, GetAmenitiesFromLuxuries=1, GetAmenitiesFromCivics=0,
  GetAmenitiesFromEntertainment=2, GetHousing=9, GetFoodSurplus=1,
  GetHappiness=4, GetTurnsUntilGrowth=10

### GameCore_Tuner -- ABSENT (nil)
GetAmenitiesNeeded, GetAmenitiesFromGreatPeople, GetAmenitiesFromReligion,
GetAmenitiesFromWarWeariness, GetAmenitiesFromBonusTypes,
GetAmenitiesLostFromWarWeariness, GetRouteMaintenance,
GetTotalImprovementMaintenance, GetGoldSurplus, GetTotalGoldIncome,
GetTotalGoldExpenditure, BuildQueue:GetCurrentProductionTypeName,
BuildQueue:GetCurrentProductionTypeHash, BuildQueue:GetProductionYield

### GameCore_Tuner -- PRESENT BUT "Not Implemented."
BuildQueue:CanProduce, BuildQueue:GetTurnsLeft

### InGame (UI state) -- WORKING where GameCore stubs out
BuildQueue:CanProduce(hash, true) -> bool
BuildQueue:GetTurnsLeft(hash) -> int
Rome, turn 59: offers BUILDING_GRANARY 8, BUILDING_LIBRARY 11,
BUILDING_HANGING_GARDENS 23. GameInfo.Buildings() iterates 128 rows.

## Not verified
Diplomatic state, peace deals, combat odds. Out of the chosen first-cut scope.
