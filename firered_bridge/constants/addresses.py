from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from ..memory.symbols import sym_addr, sym_addrs, sym_entry

# =============================================================================
# Addresses, offsets, and static constants
#
# NOTE: This file is generated from the original game_state.py layout and is
# intended to be a stable import surface for other modules.
# =============================================================================

# Bag + security key
BAG_MAIN_ADDR = sym_addr("gBagPockets")

# Player avatar
PLAYER_AVATAR_ADDR = sym_addr("gPlayerAvatar")
PLAYER_AVATAR_FLAG_MACH_BIKE = 1 << 1
PLAYER_AVATAR_FLAG_ACRO_BIKE = 1 << 2
PLAYER_AVATAR_FLAG_BIKING = PLAYER_AVATAR_FLAG_MACH_BIKE | PLAYER_AVATAR_FLAG_ACRO_BIKE
PLAYER_AVATAR_FLAG_SURFING = (1 << 3)
PLAYER_AVATAR_FLAG_DIVING = (1 << 4)

# Battle flag
# FireRed: gMain.inBattle byte is at offset 0x439 in struct Main.
IN_BATTLE_BIT_ADDR = sym_addr("gMain") + 0x439
IN_BATTLE_BITMASK = 0x02
GSAFARI_ZONE_STEP_COUNTER_ADDR = sym_addr("gSafariZoneStepCounter")

# Script lock (field control)
SCRIPT_LOCK_FIELD_CONTROLS = sym_addr("sLockFieldControls")

# Palette fade (transitions / full input lock)
GPALETTE_FADE_ADDR = sym_addr("gPaletteFade", size=0x0C)
PALETTE_FADE_BITFIELDS_OFFSET = 0x04
PALETTE_FADE_ACTIVE_MASK32 = 0x80000000  # bit 31 in the first 32-bit bitfield word

# Global script context (for detecting script waits that accept player input vs non-input waits)
SGLOBAL_SCRIPT_CONTEXT_STATUS_ADDR = sym_addr("sGlobalScriptContextStatus")
SGLOBAL_SCRIPT_CONTEXT_ADDR = sym_addr("sGlobalScriptContext", size=0x74)
SCRIPT_CONTEXT_MODE_OFFSET = 0x01
SCRIPT_CONTEXT_NATIVE_PTR_OFFSET = 0x04
SCRIPT_MODE_STOPPED = 0
SCRIPT_MODE_BYTECODE = 1
SCRIPT_MODE_NATIVE = 2
WAIT_FOR_A_OR_B_PRESS_ADDR = sym_addr("WaitForAorBPress")
IS_FIELD_MESSAGE_BOX_HIDDEN_ADDR = sym_addr("IsFieldMessageBoxHidden")

# Text / Dialog detection
# gStringVar buffers (EWRAM) - used for constructing text
GSTRINGVAR1_ADDR = sym_addr("gStringVar1")  # 256 bytes
GSTRINGVAR2_ADDR = sym_addr("gStringVar2")  # 256 bytes
GSTRINGVAR3_ADDR = sym_addr("gStringVar3")  # 256 bytes
GSTRINGVAR4_ADDR = sym_addr("gStringVar4")  # 1000 bytes (main message buffer)
GSTRINGVAR1_SIZE = 0x100
GSTRINGVAR2_SIZE = 0x100
GSTRINGVAR3_SIZE = 0x100
GSTRINGVAR4_SIZE = 0x3E8

# TextPrinter structure (for reading currently displayed text)
# sTextPrinters address from pokefirered.sym
STEXTPRINTERS_ADDR = sym_addr("sTextPrinters")
# sizeof(struct TextPrinter) is 0x24 (0x22 fields + 2 bytes padding for 4-byte alignment).
TEXTPRINTER_SIZE = 0x24
TEXTPRINTER_CURRENTCHAR_OFFSET = 0x00
TEXTPRINTER_ACTIVE_OFFSET = 0x1B
TEXTPRINTER_STATE_OFFSET = 0x1C

# Battle/message buffers
GDISPLAYEDSTRINGBATTLE_ADDR = sym_addr("gDisplayedStringBattle")
GDISPLAYEDSTRINGBATTLE_SIZE = 300
GBATTLETEXTBUFF1_ADDR = sym_addr("gBattleTextBuff1")
GBATTLETEXTBUFF2_ADDR = sym_addr("gBattleTextBuff2")
GBATTLETEXTBUFF3_ADDR = sym_addr("gBattleTextBuff3")
GBATTLETEXTBUFF_SIZE = 0x10

# Battle state (pokefirered/include/battle.h, pokefirered/include/pokemon.h)
GBATTLESCRIPTCURRINSTR_ADDR = sym_addr("gBattlescriptCurrInstr")
GBATTLECOMMUNICATION_ADDR = sym_addr("gBattleCommunication")
GBATTLECOMMUNICATION_SIZE = 8  # BATTLE_COMMUNICATION_ENTRIES_COUNT

GBATTLETYPEFLAGS_ADDR = sym_addr("gBattleTypeFlags")
GBATTLERSCOUNT_ADDR = sym_addr("gBattlersCount")
GBATTLERPARTYINDEXES_ADDR = sym_addr("gBattlerPartyIndexes")
GBATTLERPOSITIONS_ADDR = sym_addr("gBattlerPositions")
GBATTLEMONS_ADDR = sym_addr("gBattleMons")
GABSENTBATTLERFLAGS_ADDR = sym_addr("gAbsentBattlerFlags")
GACTIVEBATTLER_ADDR = sym_addr("gActiveBattler")
GACTIONSELECTIONCURSOR_ADDR = sym_addr("gActionSelectionCursor")
GMOVESELECTIONCURSOR_ADDR = sym_addr("gMoveSelectionCursor")
GBATTLERCONTROLLERFUNCS_ADDR = sym_addr("gBattlerControllerFuncs")
GMULTIUSEPLAYERCURSOR_ADDR = sym_addr("gMultiUsePlayerCursor")
GBATTLE_BG0_Y_ADDR = sym_addr("gBattle_BG0_Y")

BATTLE_MAX_BATTLERS = 4
BATTLE_POKEMON_SIZE = 0x58  # sizeof(struct BattlePokemon) in pokefirered/include/pokemon.h
GBATTLEMONS_SIZE = BATTLE_MAX_BATTLERS * BATTLE_POKEMON_SIZE

# Battler position bits (pokefirered/include/constants/battle.h)
BATTLER_BIT_SIDE = 1
BATTLER_BIT_FLANK = 2

# Battle type flags (subset) (pokefirered/include/constants/battle.h)
BATTLE_TYPE_DOUBLE = 1 << 0
BATTLE_TYPE_TRAINER = 1 << 3
BATTLE_TYPE_SAFARI = 1 << 7

# GBA display constants (pokefirered/include/gba/defines.h)
DISPLAY_HEIGHT = 160

# Battle input handler addresses (used to infer battle UI state)
BATTLE_HANDLE_INPUT_CHOOSE_ACTION_ADDRS = sym_addrs("HandleInputChooseAction")
BATTLE_HANDLE_INPUT_CHOOSE_MOVE_ADDRS = sym_addrs("HandleInputChooseMove")
BATTLE_HANDLE_INPUT_CHOOSE_TARGET_ADDRS = sym_addrs("HandleInputChooseTarget")
BATTLE_PLAYER_HANDLE_YES_NO_INPUT_ADDRS = sym_addrs("PlayerHandleUnknownYesNoBox")

# Start Menu structure (from pokefirered.sym)
START_MENU_CURSOR_POS_ADDR = sym_addr("sStartMenuCursorPos")
START_MENU_NUM_ACTIONS_ADDR = sym_addr("sNumStartMenuItems")
START_MENU_ACTIONS_ADDR = sym_addr("sStartMenuOrder")
START_MENU_WINDOW_ID_ADDR = sym_addr("sStartMenuWindowId")  # 0xFF = not visible
WINDOW_NONE = 0xFF

# gMenuCallback points to StartCB_HandleInput when START menu is active
GMENU_CALLBACK_ADDR = sym_addr("sStartMenuCallback")
HANDLE_START_MENU_INPUT_ADDR = sym_addr("StartCB_HandleInput")
# Start menu is driven by tasks (start_menu.c). Task-based detection is more robust than relying
# on sStartMenuWindowId, which can become stale when windows are freed by CleanupOverworldWindowsAndTilemaps().
TASK_SHOW_START_MENU_ADDR = sym_addr("Task_StartMenuHandleInput")
START_MENU_TASK_ADDR = sym_addr("Task_StartMenuHandleInput")

# Start menu action IDs to names
START_MENU_ACTION_NAMES = {
    0: "POKEDEX",
    1: "POKEMON",
    2: "BAG",
    3: "PLAYER",
    4: "SAVE",
    5: "OPTION",
    6: "EXIT",
    7: "RETIRE",  # Safari Zone
    8: "PLAYER",  # Link mode
}

# Bag Menu structure (FireRed)
# - sBagMenuDisplay: pointer to heap-allocated BagMenuAlloc metadata.
# - gBagMenuState: persistent bag state (pocket + cursor/scroll per pocket).
GBAGMENU_PTR_ADDR = sym_addr("sBagMenuDisplay")
GBAGPOSITION_ADDR = sym_addr("gBagMenuState")
# FireRed exposes context-menu state via dedicated globals (item_menu.c).
SCONTEXT_MENU_ITEMS_PTR_ADDR = sym_addr("sContextMenuItemsPtr")
SCONTEXT_MENU_NUM_ITEMS_ADDR = sym_addr("sContextMenuNumItems")

# Bag menu list menu callbacks (pokefirered/src/item_menu.c)
BAGMENU_MOVE_CURSOR_CALLBACK_ADDR = sym_addr("BagListMenuMoveCursorFunc")
BAGMENU_ITEM_PRINT_CALLBACK_ADDR = sym_addr("BagListMenuItemPrintFunc")
LIST_MENU_DUMMY_TASK_ADDR = sym_addr("ListMenuDummyTask")
TASK_BAG_MENU_HANDLE_INPUT_ADDR = sym_addr("Task_BagMenu_HandleInput")
TASK_ITEM_CONTEXT_MENU_BY_LOCATION_ADDR = sym_addr("Task_ItemContextMenuByLocation")
TASK_FIELD_ITEM_CONTEXT_MENU_HANDLE_INPUT_ADDR = sym_addr("Task_FieldItemContextMenuHandleInput")

# Bag context menu action table (pokefirered/src/item_menu.c)
SITEM_MENU_ACTIONS_ADDR = sym_addr("sItemMenuContextActions")
# gBagMenuState offsets:
#   0: bagCallback (4 bytes)
#   4: location (u8)
#   5: bagOpen (bool8)
#   6: pocket (u16)
#   8: itemsAbove[NUM_BAG_POCKETS_NO_CASES] (u16[3])
#   14: cursorPos[NUM_BAG_POCKETS_NO_CASES] (u16[3])
BAGPOSITION_POCKET_OFFSET = 6
BAGPOSITION_CURSOR_OFFSET = 14
BAGPOSITION_SCROLL_OFFSET = 8

# struct BagMenuAlloc offsets (pokefirered/src/item_menu.c)
# (used when sBagMenuDisplay is allocated)
BAG_MENU_NUM_POCKETS = 3
BG_SCREEN_SIZE = 0x800  # kept for compatibility with legacy code paths
BAGMENU_WINDOW_IDS_OFFSET = 0  # not used in FireRed path
BAGMENU_FLAGS_OFFSET = 5  # packed mode/icon/description-inhibit flags byte
BAGMENU_HIDE_CLOSE_BAG_MASK = 0x80
BAGMENU_CONTEXT_MENU_ITEMS_PTR_OFFSET = 0  # not used in FireRed path
BAGMENU_CONTEXT_MENU_NUM_ITEMS_OFFSET = 0  # not used in FireRed path
BAGMENU_NUM_ITEM_STACKS_OFFSET = 10  # nItems[3]
BAGMENU_NUM_SHOWN_ITEMS_OFFSET = 13  # maxShowed[3]

# ListMenu struct offsets within a task (pokefirered/include/list_menu.h)
LISTMENU_TEMPLATE_MOVECURSORFUNC_OFFSET = 0x04
LISTMENU_TEMPLATE_ITEMPRINTFUNC_OFFSET = 0x08
LISTMENU_TEMPLATE_WINDOWID_OFFSET = 0x10
LISTMENU_SCROLL_OFFSET = 0x18
LISTMENU_SELECTED_ROW_OFFSET = 0x1A

# gMain structure for checking active callback
GMAIN_ADDR = sym_addr("gMain")
GMAIN_CALLBACK2_OFFSET = 0x04  # gMain.callback2

# CB2_BagMenuRun - the callback when bag menu is active
CB2_BAG_MENU_RUN_ADDR = sym_addr("CB2_BagMenuRun")
CB2_BAG_ADDR = sym_addr("CB2_BagMenuFromStartMenu")  # during bag init (before CB2_BagMenuRun)

# TM Case UI (tm_case.c) - separate from the regular Bag callback/task flow.
STM_CASE_STATIC_RESOURCES_ADDR = sym_addr("sTMCaseStaticResources")
STM_CASE_DYNAMIC_RESOURCES_PTR_ADDR = sym_addr("sTMCaseDynamicResources")
CB2_TM_CASE_IDLE_ADDR = sym_addr("CB2_Idle", near="InitTMCase")
CB2_TM_CASE_SETUP_ADDR = sym_addr("CB2_SetUpTMCaseUI_Blocking")
TASK_TM_CASE_HANDLE_LIST_INPUT_ADDR = sym_addr("Task_HandleListInput", near="InitTMCase")
TASK_TM_CASE_SELECTED_FIELD_ADDR = sym_addr("Task_SelectedTMHM_Field", near="InitTMCase")
TASK_TM_CASE_CONTEXT_MENU_HANDLE_INPUT_ADDR = sym_addr("Task_ContextMenu_HandleInput", near="InitTMCase")
TMCASE_MENU_ACTIONS_ADDR = sym_addr("sMenuActions", near="InitTMCase")

# tm_case.c static/dynamic runtime structs
TMCASE_STATIC_MENU_TYPE_OFFSET = 0x04
TMCASE_STATIC_ALLOW_SELECT_CLOSE_OFFSET = 0x05
TMCASE_STATIC_SELECTED_ROW_OFFSET = 0x08
TMCASE_STATIC_SCROLL_OFFSET = 0x0A
TMCASE_DYNAMIC_MAX_TMS_SHOWN_OFFSET = 0x05
TMCASE_DYNAMIC_NUM_TMS_OFFSET = 0x06
TMCASE_DYNAMIC_CONTEXT_MENU_WINDOW_ID_OFFSET = 0x07
TMCASE_DYNAMIC_MENU_ACTION_INDICES_PTR_OFFSET = 0x0C
TMCASE_DYNAMIC_NUM_MENU_ACTIONS_OFFSET = 0x10

# Map-load / transitions
CB2_DO_CHANGE_MAP_ADDR = sym_addr("CB2_DoChangeMap")
CB2_LOAD_MAP_ADDR = sym_addr("CB2_LoadMap")

# CB2_TrainerCard - the callback when trainer card is displayed
CB2_TRAINER_CARD_ADDR = sym_addr("CB2_TrainerCard")

# Overworld callback2
CB2_OVERWORLD_ADDR = sym_addr("CB2_Overworld")

# Shop (Poké Mart) buy menu callback (item list UI)
CB2_BUY_MENU_ADDR = sym_addr("CB2_BuyMenu")

# Party (START -> POKéMON) menu callbacks
CB2_INIT_PARTY_MENU_ADDR = sym_addr("CB2_InitPartyMenu")
CB2_UPDATE_PARTY_MENU_ADDR = sym_addr("CB2_UpdatePartyMenu")

# Fly (region map) callbacks
CB2_OPEN_FLY_MAP_ADDR = sym_addr("CB2_OpenFlyMap")
CB2_FLY_MAP_ADDR = sym_addr("CB2_RegionMap")  # active callback once the fly map UI loop is running

# Fly map state (region_map.c)
# sFlyMap is a pointer to the EWRAM struct allocated by CB2_OpenFlyMap.
SFLYMAP_PTR_ADDR = sym_addr("sFlyMap")
# FireRed keeps RegionMap and MapCursor as separate EWRAM heap pointers.
SREGIONMAP_PTR_ADDR = sym_addr("sRegionMap")
SMAPCURSOR_PTR_ADDR = sym_addr("sMapCursor")

# MainCB2 for Option Menu (local function in option_menu.c)
CB2_OPTION_MENU_ADDR = sym_addr("CB2_OptionMenu")

# Title screen main menu callbacks (main_menu.c)
CB2_MAIN_MENU_ADDR = sym_addr("CB2_MainMenu")
CB2_INIT_MAIN_MENU_ADDR = sym_addr("CB2_InitMainMenu")
CB2_REINIT_MAIN_MENU_ADDR = CB2_MAIN_MENU_ADDR

# Title screen (Press Start) callbacks/tasks (title_screen.c)
CB2_INIT_TITLE_SCREEN_ADDR = sym_addr("CB2_InitTitleScreen")
CB2_TITLE_SCREEN_ADDR = sym_addr("MainCB2", near="CB2_InitTitleScreen")
TASK_TITLE_SCREEN_PHASE1_ADDR = sym_addr("Task_TitleScreenTimer")
TASK_TITLE_SCREEN_PHASE2_ADDR = sym_addr("Task_TitleScreenMain")
TASK_TITLE_SCREEN_PHASE3_ADDR = sym_addr("Task_TitleScreen_BlinkPressStart")

# New game (Professor Birch speech) gender menu (main_menu.c)
TASK_NEW_GAME_BIRCH_SPEECH_CHOOSE_GENDER_ADDR = sym_addr("Task_OakSpeech_AskPlayerGender")
TASK_NEW_GAME_BIRCH_SPEECH_SLIDE_OUT_OLD_GENDER_SPRITE_ADDR = sym_addr("Task_OakSpeech_ShowGenderOptions")
TASK_NEW_GAME_BIRCH_SPEECH_SLIDE_IN_NEW_GENDER_SPRITE_ADDR = sym_addr("Task_OakSpeech_HandleGenderInput")
# Whiteout recovery message task (field_screen_effect.c)
TASK_RUSH_INJURED_POKEMON_TO_CENTER_ADDR = sym_addr("Task_RushInjuredPokemonToCenter")
GTEXT_BIRCH_BOY_ADDR = sym_addr("gText_Boy")
GTEXT_BIRCH_GIRL_ADDR = sym_addr("gText_Girl")

# New game controls guide (oak_speech.c)
SOAK_SPEECH_RESOURCES_PTR_ADDR = sym_addr("sOakSpeechResources")
OAK_SPEECH_CURRENT_PAGE_OFFSET = 0x12  # struct OakSpeechResources.currentPage
OAK_SPEECH_WINDOW_IDS_OFFSET = 0x14  # struct OakSpeechResources.windowIds[NUM_INTRO_WINDOWS]
OAK_SPEECH_WIN_INTRO_TEXTBOX_INDEX = 0
TASK_CONTROLS_GUIDE_LOAD_PAGE_ADDR = sym_addr("Task_ControlsGuide_LoadPage")
TASK_CONTROLS_GUIDE_HANDLE_INPUT_ADDR = sym_addr("Task_ControlsGuide_HandleInput")
TASK_CONTROLS_GUIDE_CHANGE_PAGE_ADDR = sym_addr("Task_ControlsGuide_ChangePage")
TASK_CONTROLS_GUIDE_CLEAR_ADDR = sym_addr("Task_ControlsGuide_Clear")
GTEXT_CONTROLS_ADDR = sym_addr("gText_Controls")
GTEXT_ABUTTON_NEXT_ADDR = sym_addr("gText_ABUTTONNext")
GTEXT_ABUTTON_NEXT_BBUTTON_BACK_ADDR = sym_addr("gText_ABUTTONNext_BBUTTONBack")
GCONTROLS_GUIDE_TEXT_INTRO_ADDR = sym_addr("gControlsGuide_Text_Intro")
GCONTROLS_GUIDE_TEXT_DPAD_ADDR = sym_addr("gControlsGuide_Text_DPad")
GCONTROLS_GUIDE_TEXT_ABUTTON_ADDR = sym_addr("gControlsGuide_Text_AButton")
GCONTROLS_GUIDE_TEXT_BBUTTON_ADDR = sym_addr("gControlsGuide_Text_BButton")
GCONTROLS_GUIDE_TEXT_STARTBUTTON_ADDR = sym_addr("gControlsGuide_Text_StartButton")
GCONTROLS_GUIDE_TEXT_SELECTBUTTON_ADDR = sym_addr("gControlsGuide_Text_SelectButton")
GCONTROLS_GUIDE_TEXT_LRBUTTONS_ADDR = sym_addr("gControlsGuide_Text_LRButtons")
CONTROLS_GUIDE_NUM_PAGES = 3
TASK_PIKACHU_INTRO_LOAD_PAGE1_ADDR = sym_addr("Task_PikachuIntro_LoadPage1")
TASK_PIKACHU_INTRO_HANDLE_INPUT_ADDR = sym_addr("Task_PikachuIntro_HandleInput")
TASK_PIKACHU_INTRO_CLEAR_ADDR = sym_addr("Task_PikachuIntro_Clear")
GPIKACHU_INTRO_TEXT_PAGE1_ADDR = sym_addr("gPikachuIntro_Text_Page1")
GPIKACHU_INTRO_TEXT_PAGE2_ADDR = sym_addr("gPikachuIntro_Text_Page2")
GPIKACHU_INTRO_TEXT_PAGE3_ADDR = sym_addr("gPikachuIntro_Text_Page3")
PIKACHU_INTRO_NUM_PAGES = 3

# Quest Log playback recap screen ("Previously on your quest...")
# quest_log.c:
#   gQuestLogState / gQuestLogPlaybackState gate playback mode
#   sWindowIds[3] stores [top bar, bottom bar, description] windows for recap overlay
GQUEST_LOG_STATE_ADDR = sym_addr("gQuestLogState")
GQUEST_LOG_PLAYBACK_STATE_ADDR = sym_addr("gQuestLogPlaybackState")
SQUEST_LOG_WINDOW_IDS_ADDR = sym_addr("sWindowIds", near="gQuestLogState", fallback=0x0203ADFE)

QL_STATE_RECORDING = 1
QL_STATE_PLAYBACK = 2
QL_STATE_PLAYBACK_LAST = 3

QL_PLAYBACK_STATE_STOPPED = 0
QL_PLAYBACK_STATE_RUNNING = 1
QL_PLAYBACK_STATE_RECORDING = 2
QL_PLAYBACK_STATE_ACTION_END = 3
QL_PLAYBACK_STATE_RECORDING_NO_DELAY = 4

QUEST_LOG_WIN_TOP_BAR_INDEX = 0
QUEST_LOG_WIN_BOTTOM_BAR_INDEX = 1
QUEST_LOG_WIN_DESCRIPTION_INDEX = 2
QUEST_LOG_WINDOW_COUNT = 3

GTEXT_QUESTLOG_PREVIOUSLY_ON_YOUR_QUEST_ADDR = sym_addr("gText_QuestLog_PreviouslyOnYourQuest")
GTEXT_QUESTLOG_SAVED_GAME_AT_LOCATION_ADDR = sym_addr("gText_QuestLog_SavedGameAtLocation")

# Naming screen (naming_screen.c)
CB2_LOAD_NAMING_SCREEN_ADDR = sym_addr("CB2_LoadNamingScreen")
CB2_NAMING_SCREEN_ADDR = sym_addr("CB2_NamingScreen")
TASK_NAMING_SCREEN_ADDR = sym_addr("Task_NamingScreen")
SNAMING_SCREEN_PTR_ADDR = sym_addr("sNamingScreen")
GSPRITES_ADDR = sym_addr("gSprites")

# Pokémon Summary Screen (pokemon_summary_screen.c)
CB2_INIT_SUMMARY_SCREEN_ADDR = sym_addr("CB2_ShowPokemonSummaryScreen")
CB2_SUMMARY_SCREEN_ADDR = sym_addr("CB2_RunPokemonSummaryScreen")
SMON_SUMMARY_SCREEN_PTR_ADDR = sym_addr("sMonSummaryScreen")
SMOVE_SELECTION_CURSOR_POS_ADDR = sym_addr("sMoveSelectionCursorPos")
SMOVE_SWAP_CURSOR_POS_ADDR = sym_addr("sMoveSwapCursorPos")
TASK_SUMMARY_HANDLE_REPLACE_MOVE_INPUT_ADDR = sym_addr("Task_HandleReplaceMoveYesNoInput")
TASK_SUMMARY_HANDLE_CANT_FORGET_HMS_MOVES_ADDR = sym_addr("Task_HandleStopLearningMoveYesNoInput")

# ROM tables used to reconstruct move details on the summary screen
GBATTLE_MOVES_ADDR = sym_addr("gBattleMoves")
BATTLE_MOVE_SIZE = 12  # sizeof(struct BattleMove) (GBA alignment)
GMOVE_DESCRIPTION_POINTERS_ADDR = sym_addr("gMoveDescriptionPointers")

# SaveBlock2 structure offsets (for trainer card info)
# gSaveBlock2Ptr (from pokefirered.sym)
GSAVEBLOCK2_PTR_ADDR = sym_addr("gSaveBlock2Ptr")
SB2_PLAYER_NAME_OFFSET = 0x00  # 8 bytes
SB2_PLAYER_GENDER_OFFSET = 0x08  # 1 byte
SB2_TRAINER_ID_OFFSET = 0x0A  # 4 bytes (2 bytes public ID, 2 bytes secret ID)
SB2_PLAY_TIME_HOURS_OFFSET = 0x0E  # 2 bytes
SB2_PLAY_TIME_MINUTES_OFFSET = 0x10  # 1 byte
SB2_PLAY_TIME_SECONDS_OFFSET = 0x11  # 1 byte
SB2_ENCRYPTION_KEY_OFFSET = 0xF20  # 4 bytes (pokefirered/include/global.h)
SB2_PYRAMID_LIGHT_RADIUS_OFFSET = 0xE68  # leftover RSE data; kept for compatibility

# SaveBlock1 structure offsets
# gSaveBlock1Ptr (from pokefirered.sym)
GSAVEBLOCK1_PTR_ADDR = sym_addr("gSaveBlock1Ptr")
SB1_FLASH_LEVEL_OFFSET = 0x30  # u8 flashLevel (0=bright, 1..7 radius, 8=black)
SB1_MONEY_OFFSET = 0x0290  # 4 bytes (encrypted with encryptionKey)
SB1_PC_ITEMS_OFFSET = 0x0298  # struct ItemSlot[PC_ITEMS_COUNT]
SB1_TRAINER_REMATCHES_OFFSET = 0x063A  # u8 trainerRematches[MAX_REMATCH_ENTRIES]
SB1_OBJECT_EVENT_TEMPLATES_OFFSET = 0x08E0  # struct ObjectEventTemplate[OBJECT_EVENT_TEMPLATES_COUNT]
SB1_FLAGS_OFFSET = 0x0EE0  # Flags array
SB1_GAME_STATS_OFFSET = 0x1200  # u32 gameStats[NUM_GAME_STATS] (encrypted with encryptionKey)

# Legacy aliases (kept for compat with older code/tests)
SECURITY_KEY_POINTER_ADDR = GSAVEBLOCK2_PTR_ADDR
SECURITY_KEY_OFFSET = SB2_ENCRYPTION_KEY_OFFSET
SAVESTATE_OBJECT_POINTER_ADDR = GSAVEBLOCK1_PTR_ADDR
SAVESTATE_MONEY_OFFSET = SB1_MONEY_OFFSET
SAVESTATE_FLAGS_OFFSET = SB1_FLAGS_OFFSET

# Badge flags
SYSTEM_FLAGS_START = 0x800
FLAG_BADGE01 = SYSTEM_FLAGS_START + 0x20  # 0x820
NUM_BADGES = 8
FLAG_SYS_POKEMON_GET = SYSTEM_FLAGS_START + 0x28  # 0x828
FLAG_SYS_POKEDEX_GET = SYSTEM_FLAGS_START + 0x29  # 0x829
FLAG_SYS_GAME_CLEAR = SYSTEM_FLAGS_START + 0x2C  # 0x82C (Champion / Hall of Fame unlocked)
FLAG_SYS_SAFARI_MODE = SYSTEM_FLAGS_START + 0x00  # 0x800
FLAG_SYS_USE_FLASH = SYSTEM_FLAGS_START + 0x06  # 0x806
FLAG_SYS_USE_STRENGTH = SYSTEM_FLAGS_START + 0x05  # 0x805
FLAG_SYS_NATIONAL_DEX = SYSTEM_FLAGS_START + 0x40  # 0x840
FLAG_SYS_PC_LANETTE = SYSTEM_FLAGS_START + 0x4B  # 0x8AB (PC name becomes "Lanette's PC")

# Story progression / overworld state flags (pokefirered/include/constants/flags.h)
FLAG_HIDE_HIDEOUT_GIOVANNI = 0x038
FLAG_HIDE_SAFFRON_ROCKETS = 0x03E
FLAG_HIDE_SS_ANNE = 0x087
FLAG_GOT_HM03 = 0x239
FLAG_GOT_POKE_FLUTE = 0x23D

# Elite Four / Champion flags (pokefirered/include/constants/flags.h)
FLAG_DEFEATED_LORELEI = 0x4B8
FLAG_DEFEATED_BRUNO = 0x4B9
FLAG_DEFEATED_AGATHA = 0x4BA
FLAG_DEFEATED_LANCE = 0x4BB
FLAG_DEFEATED_CHAMP = 0x4BC

# Vars (saveblock1.vars)
VARS_START = 0x4000
SB1_VARS_OFFSET = 0x1000
VAR_NATIONAL_DEX = 0x404E
NATIONAL_DEX_VAR_VALUE = 0x6258

# Pokedex (saveblock2.pokedex)
SB2_POKEDEX_OFFSET = 0x18
POKEDEX_NATIONAL_MAGIC_OFFSET = 0x03
POKEDEX_OWNED_OFFSET = 0x10
NUM_DEX_FLAG_BYTES = 0x34  # FireRed: ROUND_BITS_TO_BYTES(NUM_SPECIES) = 52
NATIONAL_MAGIC_VALUE = 0xB9
KANTO_DEX_COUNT = 151  # KANTO_DEX_COUNT (NATIONAL_DEX_MEW)
NATIONAL_DEX_COUNT = 386  # NATIONAL_DEX_DEOXYS

# Pokédex UI (pokefirered/src/pokedex_screen.c)
CB2_OPEN_POKEDEX_ADDR = sym_addr("CB2_OpenPokedexFromStartMenu")
CB2_POKEDEX_ADDR = sym_addr("CB2_PokedexScreen")
SPOKEDEXVIEW_PTR_ADDR = sym_addr("sPokedexScreenData")
GPOKEDEXENTRIES_ADDR, GPOKEDEXENTRIES_SIZE, _ = sym_entry("gPokedexEntries")

# Pokédex task state machines (pokedex_screen.c)
TASK_POKEDEX_SCREEN_ADDR = sym_addr("Task_PokedexScreen")
TASK_DEXSCREEN_NUMERICAL_ORDER_ADDR = sym_addr("Task_DexScreen_NumericalOrder")
TASK_DEXSCREEN_CHARACTERISTIC_ORDER_ADDR = sym_addr("Task_DexScreen_CharacteristicOrder")
TASK_DEXSCREEN_CATEGORY_SUBMENU_ADDR = sym_addr("Task_DexScreen_CategorySubmenu")
TASK_DEXSCREEN_SHOW_MON_PAGE_ADDR = sym_addr("Task_DexScreen_ShowMonPage")
TASK_DEXSCREEN_REGISTER_NON_KANTO_MON_ADDR = sym_addr("Task_DexScreen_RegisterNonKantoMonBeforeNationalDex")
TASK_DEXSCREEN_REGISTER_MON_TO_POKEDEX_ADDR = sym_addr("Task_DexScreen_RegisterMonToPokedex")

# Pokédex entry strings (pokedex_screen.c)
GTEXT_5MARKS_POKEMON_ADDR = sym_addr("gText_5Dashes")
GTEXT_HT_HEIGHT_ADDR = sym_addr("gText_HT")
GTEXT_WT_WEIGHT_ADDR = sym_addr("gText_WT")

# Species -> National Dex number table (pokemon.c)
SSPECIES_TO_NATIONAL_POKEDEX_NUM_ADDR, SSPECIES_TO_NATIONAL_POKEDEX_NUM_SIZE, _ = sym_entry(
    "sSpeciesToNationalPokedexNum"
)

# Options in SaveBlock2 (offset 0x14 is a bitfield)
SB2_OPTIONS_OFFSET = 0x14
SB2_BUTTON_MODE_OFFSET = 0x13  # optionsButtonMode (u8)

# Option menu item names
OPTION_TEXT_SPEED_NAMES = ["SLOW", "MID", "FAST"]
OPTION_BATTLE_SCENE_NAMES = ["ON", "OFF"]
OPTION_BATTLE_STYLE_NAMES = ["SHIFT", "SET"]
OPTION_SOUND_NAMES = ["MONO", "STEREO"]
OPTION_BUTTON_MODE_NAMES = ["NORMAL", "LR", "L=A"]

# Option menu callbacks/tasks (option_menu.c)
CB2_INIT_OPTION_MENU_ADDR = sym_addr("CB2_InitOptionMenu")
TASK_OPTION_MENU_SAVE_ADDR = sym_addr("Task_OptionMenu")
TASK_OPTION_MENU_FADEOUT_ADDR = sym_addr("Task_OptionMenu")
# Live option menu state (option_menu.c: static EWRAM_DATA struct OptionMenu *sOptionMenuPtr)
SOPTION_MENU_PTR_ADDR = sym_addr("sOptionMenuPtr")
OPTION_MENU_OPTION_ARRAY_OFFSET = 0x00
OPTION_MENU_CURSOR_POS_OFFSET = 0x0E

# Option menu items (for cursor position)
OPTION_MENU_ITEMS = ["TEXT SPEED", "BATTLE SCENE", "BATTLE STYLE", "SOUND", "BUTTON MODE", "FRAME", "CANCEL"]

# Title screen main menu variants (main_menu.c enum)
TITLE_MENU_VARIANT_NAMES = {
    0: "HAS_NO_SAVED_GAME",
    1: "HAS_SAVED_GAME",
    2: "HAS_MYSTERY_GIFT",
    3: "HAS_MYSTERY_EVENTS",
}

TITLE_MENU_OPTIONS = {
    # FireRed main_menu.c:
    # MAIN_MENU_NEWGAME    -> NEW GAME
    # MAIN_MENU_CONTINUE   -> CONTINUE, NEW GAME
    # MAIN_MENU_MYSTERYGIFT-> CONTINUE, NEW GAME, MYSTERY GIFT
    0: ["NEW GAME"],
    1: ["CONTINUE", "NEW GAME"],
    2: ["CONTINUE", "NEW GAME", "MYSTERY GIFT"],
}

# Task system for reading menu cursor position
GTASKS_ADDR = sym_addr("gTasks")
TASK_SIZE = 0x28  # 40 bytes per task
TASK_FUNC_OFFSET = 0x00  # TaskFunc pointer
TASK_ISACTIVE_OFFSET = 0x04
TASK_DATA_OFFSET = 0x08  # data[0] starts here
NUM_TASKS = 16

# Pokémon Storage System (pokemon_storage_system.c)
CB2_POKE_STORAGE_ADDR = sym_addr("CB2_PokeStorage")
CB2_RETURN_TO_POKE_STORAGE_ADDR = sym_addr("CB2_ReturnToPokeStorage")
TASK_POKEMON_STORAGE_PC_MAIN_MENU_ADDR = sym_addr("Task_PCMainMenu")
SPOKE_STORAGE_MAIN_MENU_TEXTS_ADDR = sym_addr("sMainMenuTexts")
SPOKE_STORAGE_PTR_ADDR = sym_addr("gStorage")
SPOKE_STORAGE_CHOOSE_BOX_MENU_PTR_ADDR = sym_addr("sChooseBoxMenu")
SPOKE_STORAGE_IN_PARTY_MENU_ADDR = sym_addr("sInPartyMenu")
SPOKE_STORAGE_CURRENT_BOX_OPTION_ADDR = sym_addr("sCurrentBoxOption")
SPOKE_STORAGE_DEPOSIT_BOX_ID_ADDR = sym_addr("sDepositBoxId")
SPOKE_STORAGE_CURSOR_AREA_ADDR = sym_addr("sCursorArea")
SPOKE_STORAGE_CURSOR_POSITION_ADDR = sym_addr("sCursorPosition")

# Berry Crush rankings (berry_crush.c)
TASK_BERRY_CRUSH_SHOW_RANKINGS_ADDR = sym_addr("Task_ShowBerryCrushRankings")

# Option menu task functions
TASK_OPTION_MENU_FADEIN_ADDR = sym_addr("Task_OptionMenu")
TASK_OPTION_MENU_PROCESSINPUT_ADDR = sym_addr("Task_OptionMenu")

# Title screen main menu task functions (main_menu.c)
TASK_DISPLAY_MAIN_MENU_ADDR = sym_addr("Task_PrintMainMenuText")
TASK_HIGHLIGHT_SELECTED_MAIN_MENU_ITEM_ADDR = sym_addr("Task_UpdateVisualSelection")
TASK_HANDLE_MAIN_MENU_INPUT_ADDR = sym_addr("Task_HandleMenuInput")

# Menu choice system (YES/NO and other menus)
SMENU_ADDR = sym_addr("sMenu", size=0x0C)
SMENU_LEFT_OFFSET = 0x00
SMENU_TOP_OFFSET = 0x01

# =============================================================================
SMENU_CURSORPOS_OFFSET = 0x02
SMENU_MINCURSORPOS_OFFSET = 0x03
SMENU_MAXCURSORPOS_OFFSET = 0x04
SMENU_WINDOWID_OFFSET = 0x05
SMENU_FONTID_OFFSET = 0x06
SMENU_OPTIONWIDTH_OFFSET = 0x07
SMENU_OPTIONHEIGHT_OFFSET = 0x08
SMENU_COLUMNS_OFFSET = 0x09
SMENU_ROWS_OFFSET = 0x0A

SYESNO_WINDOWID_ADDR = sym_addr("sYesNoWindowId")

# Task-based menu detection (robust for shops / yes-no / multichoice)
TASK_HANDLE_YES_NO_INPUT_ADDR = sym_addr("Task_HandleYesNoMenu")
TASK_CALL_YES_OR_NO_CALLBACK_ADDR = sym_addr("Task_CallYesOrNoCallback")
TASK_HANDLE_MULTICHOICE_INPUT_ADDR = sym_addr("Task_MultichoiceMenu_HandleInput")
SMULTICHOICE_LISTS_ADDR = sym_addr("sMultichoiceLists")
TASK_CREATE_SCRIPT_LIST_MENU_ADDR = sym_addr("Task_CreateScriptListMenu")
TASK_LISTMENU_HANDLE_INPUT_ADDR = sym_addr("Task_ListMenuHandleInput")
TASK_DESTROY_LIST_MENU_ADDR = sym_addr("Task_DestroyListMenu")
TASK_SUSPEND_LIST_MENU_ADDR = sym_addr("Task_SuspendListMenu")
TASK_REDRAW_SCROLL_ARROWS_AND_WAIT_INPUT_ADDR = sym_addr("Task_RedrawScrollArrowsAndWaitInput")
TASK_SHOP_MENU_ADDR = sym_addr("Task_ShopMenu")
TASK_BUY_MENU_ADDR = sym_addr("Task_BuyMenu")
TASK_BUY_HOW_MANY_DIALOGUE_INIT_ADDR = sym_addr("Task_BuyHowManyDialogueInit")
TASK_BUY_HOW_MANY_DIALOGUE_HANDLE_INPUT_ADDR = sym_addr("Task_BuyHowManyDialogueHandleInput")
TASK_RETURN_TO_ITEM_LIST_AFTER_ITEM_PURCHASE_ADDR = sym_addr("Task_ReturnToItemListAfterItemPurchase")
SMARTINFO_ADDR = sym_addr("sShopData", size=0x1C)
SHOP_MENU_ACTIONS_BUY_SELL_QUIT_ADDR = sym_addr("sShopMenuActions_BuySellQuit")
SHOP_MENU_ACTIONS_BUY_QUIT_ADDR = sym_addr("sShopMenuActions_BuyQuit")
SSHOPDATA_PTR_ADDR = sym_addr("sShopData")
GITEMS_ADDR = sym_addr("gItems")
GTEXT_QUIT_SHOPPING_ADDR = sym_addr("gText_QuitShopping")
GTEXT_CANCEL2_ADDR = sym_addr("gText_Cancel7")
GTEXT_HERE_YOU_GO_THANK_YOU_ADDR = sym_addr("gText_HereYouGoThankYou")
GTEXT_NOW_ON_ADDR = sym_addr("gText_NowOn")
TEXT_WANT_WHICH_FLOOR_ADDR = sym_addr("Text_WantWhichFloor")
SFLOOR_NAME_POINTERS_ADDR, SFLOOR_NAME_POINTERS_SIZE, _ = sym_entry("sFloorNamePointers")
SELEVATOR_CURRENT_FLOOR_WINDOW_ID_ADDR = sym_addr("sElevatorCurrentFloorWindowId")
SELEVATOR_SCROLL_ADDR = sym_addr("sElevatorScroll")
SELEVATOR_CURSOR_POS_ADDR = sym_addr("sElevatorCursorPos")

# PC (script_menu.c / player_pc.c)
MULTI_PC = 1  # constants/script_menu.h
GTEXT_WHICH_PC_SHOULD_BE_ACCESSED_ADDR = sym_addr("Text_AccessWhichPC")
GTEXT_LOG_OFF_ADDR = sym_addr("gText_LogOff")
GTEXT_HALL_OF_FAME_ADDR = sym_addr("gText_HallOfFame")
GTEXT_LANETTES_PC_ADDR = sym_addr("gText_BillSPc")
GTEXT_SOMEONES_PC_ADDR = sym_addr("gText_SomeoneSPc")
# Use the standard English prompt used by player_pc.c top menu.
# `gText_PC_WhatWouldYouLikeToDo` is a short JP variant and decodes as "?"/garbage with our charmap.
GTEXT_WHAT_WOULD_YOU_LIKE_ADDR = sym_addr("gText_WhatWouldYouLikeToDo")

# Player PC main menu (player_pc.c)
TASK_PLAYER_PC_DRAW_TOP_MENU_ADDR = sym_addr("Task_DrawPlayerPcTopMenu")
# Task_TopMenuHandleInput exists in multiple TUs; pick the one near Task_DrawPlayerPcTopMenu.
TASK_PLAYER_PC_PROCESS_MENU_INPUT_ADDR = sym_addr("Task_TopMenuHandleInput", near="Task_DrawPlayerPcTopMenu")
TASK_PLAYER_PC_PROCESS_MENU_INPUT_ADDRS = sym_addrs("Task_TopMenuHandleInput")
STOP_MENU_OPTION_ORDER_PTR_ADDR = sym_addr("sItemOrder")
STOP_MENU_NUM_OPTIONS_ADDR = sym_addr("sTopMenuItemCount")
SPLAYER_PC_MENU_ACTIONS_ADDR = sym_addr("sMenuActions_TopMenu")
MENU_ACTION_SIZE = 0x08  # struct MenuAction { const u8 *text; void (*func)(u8); }

# Player PC Item Storage (player_pc.c)
ITEM_STORAGE_MENU_PROCESS_INPUT_ADDR = sym_addr("Task_TopMenu_ItemStorageSubmenu_HandleInput")
ITEM_STORAGE_PROCESS_INPUT_ADDR = sym_addr("Task_ItemPcMain")
# Item PC (item_pc.c) runtime state
SITEM_STORAGE_MENU_PTR_ADDR = sym_addr("sStateDataPtr")
SITEM_STORAGE_LIST_MENU_STATE_ADDR = sym_addr("sListMenuState")
SITEM_PC_SUBMENU_OPTIONS_ADDR = sym_addr("sItemPcSubmenuOptions")
GPLAYER_PC_ITEM_PAGE_INFO_ADDR = sym_addr("gPlayerPcMenuManager", size=0x0C)
SITEM_STORAGE_MENU_ACTIONS_ADDR = sym_addr("sMenuActions_ItemPc")
SITEM_STORAGE_OPTION_DESCRIPTIONS_ADDR = sym_addr("sItemStorageActionDescriptionPtrs")

# Party menu (START -> POKéMON)
GPARTY_MENU_ADDR = sym_addr("gPartyMenu", size=0x14)
SPARTY_MENU_INTERNAL_PTR_ADDR = sym_addr("sPartyMenuInternal")
SCURSOR_OPTIONS_ADDR = sym_addr("sCursorOptions")
GPLAYER_PARTY_COUNT_ADDR = sym_addr("gPlayerPartyCount")
GSPECIALVAR_ITEMID_ADDR = sym_addr("gSpecialVar_ItemId")
STMHM_MOVES_ADDR = sym_addr("sTMHMMoves")
GTMHM_LEARNSETS_ADDR = sym_addr("sTMHMLearnsets")
GSPECIALVAR_0X8004_ADDR = sym_addr("gSpecialVar_0x8004")
GSPECIALVAR_0X8005_ADDR = sym_addr("gSpecialVar_0x8005")

SMARTINFO_ITEMLIST_PTR_OFFSET = 0x04
SMARTINFO_ITEMCOUNT_OFFSET = 0x10
SMARTINFO_ITEMPRICE_OFFSET = 0x08
SMARTINFO_SELECTED_ROW_OFFSET = 0x0C
SMARTINFO_SCROLL_OFFSET = 0x0E
SMARTINFO_MARTTYPE_OFFSET = 0x16
SMARTINFO_MARTTYPE_MASK = 0x000F
SMARTINFO_ITEMS_SHOWED_OFFSET = 0x12

# struct ShopData offsets (pokefirered/src/shop.c)
SHOPDATA_TOTAL_COST_OFFSET = SMARTINFO_ITEMPRICE_OFFSET
SHOPDATA_ITEMS_SHOWED_OFFSET = SMARTINFO_ITEMS_SHOWED_OFFSET
SHOPDATA_SELECTED_ROW_OFFSET = SMARTINFO_SELECTED_ROW_OFFSET
SHOPDATA_SCROLL_OFFSET_OFFSET = SMARTINFO_SCROLL_OFFSET

# struct PartyMenu offsets (pokefirered/include/party_menu.h)
GPARTY_MENU_SLOTID_OFFSET = 0x09  # s8

# struct PartyMenuInternal offsets (pokefirered/src/party_menu.c)
PARTY_MENU_INTERNAL_FLAGS_OFFSET = 0x08  # bitfields, chooseHalf is bit0
PARTY_MENU_INTERNAL_WINDOWIDS_OFFSET = 0x0C  # windowId[3]
PARTY_MENU_INTERNAL_ACTIONS_OFFSET = 0x0F  # actions[8]
PARTY_MENU_INTERNAL_NUMACTIONS_OFFSET = 0x17  # u8

# struct Item offsets (pokefirered/include/item.h). sizeof(struct Item) = 0x2C.
ITEM_STRUCT_SIZE = 0x2C
ITEM_NAME_LENGTH = 14
ITEM_PRICE_OFFSET = 0x10
ITEM_DESCRIPTION_PTR_OFFSET = 0x14

# Window system (used for reading menu/window state)
GWINDOWS_ADDR = sym_addr("gWindows")
WINDOW_SIZE = 0x0C  # sizeof(struct Window) = 8 (WindowTemplate) + 4 (tileData pointer)

# Save menu info window id (start_menu.c, not reset to WINDOW_NONE on removal)
SSAVE_INFO_WINDOWID_ADDR = sym_addr("sSaveStatsWindowId")
GTEXT_WOULD_YOU_LIKE_TO_SAVE_THE_GAME_ADDR = sym_addr("gText_WouldYouLikeToSaveTheGame")
GTEXT_ALREADY_SAVE_FILE_WOULD_LIKE_TO_OVERWRITE_ADDR = sym_addr("gText_AlreadySaveFile_WouldLikeToOverwrite")
GTEXT_DIFFERENT_GAME_FILE_ADDR = sym_addr("gText_DifferentGameFile")
GTEXT_PLAYER_SCURRIED_TO_CENTER_ADDR = sym_addr("gText_PlayerScurriedToCenter")
GTEXT_PLAYER_SCURRIED_BACK_HOME_ADDR = sym_addr("gText_PlayerScurriedBackHome")
GTEXT_TMCASE_WILL_BE_PUT_AWAY_ADDR = sym_addr("gText_TMCaseWillBePutAway")

# Some mapsec ids have special handling in GetMapNameGeneric.
# FireRed does not use FireRed's MAPSEC_DYNAMIC id.
MAPSEC_DYNAMIC = 0xFFFF
GTEXT_FERRY_ADDR = sym_addr("gText_Ferry")

# Pocket names (same order as game)
BAG_POCKET_NAMES = {
    0: "ITEMS",
    1: "KEY ITEMS",
    2: "POKé BALLS",
    3: "TM CASE",
    4: "BERRY POUCH",
}


# Species info
SPECIES_INFO_ADDR = sym_addr("gSpeciesInfo")
SPECIES_INFO_SIZE = 0x1C
SPECIES_INFO_TYPES_OFFSET = 0x06
SPECIES_INFO_GENDER_RATIO_OFFSET = 0x10
SPECIES_INFO_ABILITIES_OFFSET = 0x16

# Backup map layout (FireRed: VMap)
BACKUP_MAP_LAYOUT_ADDR = sym_addr("VMap")
BACKUP_MAP_LAYOUT_WIDTH_OFFSET = 0x00
BACKUP_MAP_LAYOUT_HEIGHT_OFFSET = 0x04
BACKUP_MAP_DATA_PTR_OFFSET = 0x08
BYTES_PER_TILE = 2
MAPGRID_UNDEFINED = 0x3FF

# Current map header
CURRENT_MAP_HEADER_ADDR = sym_addr("gMapHeader")
MAP_HEADER_MAP_LAYOUT_OFFSET = 0x00
MAP_HEADER_MAP_EVENTS_OFFSET = 0x04
MAP_HEADER_MAP_CONNECTIONS_OFFSET = 0x0C
MAP_HEADER_MAP_LAYOUT_ID_OFFSET = 0x12
MAP_HEADER_REGION_MAP_SECTION_ID_OFFSET = 0x14
MAP_HEADER_CAVE_OFFSET = 0x15  # bool8 (Flash needed when True)

# Map layout offsets
MAP_LAYOUT_WIDTH_OFFSET = 0x00
MAP_LAYOUT_HEIGHT_OFFSET = 0x04
MAP_LAYOUT_MAPGRID_OFFSET = 0x0C
MAP_LAYOUT_PRIMARY_TILESET_OFFSET = 0x10
MAP_LAYOUT_SECONDARY_TILESET_OFFSET = 0x14

# Tileset
# struct Tileset (pokefirered/include/global.fieldmap.h):
# 0x10 = callback, 0x14 = metatileAttributes pointer.
TILESET_METATILE_ATTRIBUTES_POINTER_OFFSET = 0x14
# pokefirered/include/fieldmap.h
PRIMARY_TILESET_METATILE_COUNT = 0x280  # NUM_METATILES_IN_PRIMARY (640)
TOTAL_TILESET_METATILE_COUNT = 0x400  # NUM_METATILES_TOTAL (1024)
SECONDARY_TILESET_METATILE_COUNT = TOTAL_TILESET_METATILE_COUNT - PRIMARY_TILESET_METATILE_COUNT  # 384

# Mapgrid masks
MAPGRID_METATILE_ID_MASK = 0x03FF
MAPGRID_COLLISION_MASK = 0x0C00
MAPGRID_ELEVATION_MASK = 0xF000

# Map Events (bg events - interactive tiles like PC, signs, etc.)
MAP_EVENTS_OBJECT_EVENT_COUNT_OFFSET = 0x00
MAP_EVENTS_WARP_EVENT_COUNT_OFFSET = 0x01
MAP_EVENTS_OBJECT_EVENTS_POINTER_OFFSET = 0x04
MAP_EVENTS_WARP_EVENTS_POINTER_OFFSET = 0x08
MAP_EVENTS_BG_EVENT_COUNT_OFFSET = 0x03
MAP_EVENTS_BG_EVENTS_POINTER_OFFSET = 0x10
WARP_EVENT_SIZE = 8
WARP_EVENT_X_OFFSET = 0x00
WARP_EVENT_Y_OFFSET = 0x02
WARP_EVENT_ELEVATION_OFFSET = 0x04
WARP_EVENT_WARP_ID_OFFSET = 0x05
WARP_EVENT_MAP_NUM_OFFSET = 0x06
WARP_EVENT_MAP_GROUP_OFFSET = 0x07
BG_EVENT_SIZE = 12
BG_EVENT_X_OFFSET = 0x00
BG_EVENT_Y_OFFSET = 0x02
BG_EVENT_ELEVATION_OFFSET = 0x04
BG_EVENT_KIND_OFFSET = 0x05
# struct BgEvent stores the script/hiddenItem union at offset 0x08 (aligned pointer).
BG_EVENT_SCRIPT_POINTER_OFFSET = 0x08

# BG Event kinds
BG_EVENT_KIND_SCRIPT = 0  # Signs, bookshelves, etc.
BG_EVENT_KIND_HIDDEN_ITEM = 7
BG_EVENT_KIND_SECRET_BASE = 8

# Object Events (live NPCs)
OBJECT_EVENTS_ADDR = sym_addr("gObjectEvents")
OBJECT_EVENT_COUNT = 16
OBJECT_EVENT_TEMPLATES_COUNT = 64  # FireRed constant
OBJECT_EVENT_SIZE = 0x24
OBJECT_EVENT_FLAGS_OFFSET = 0x00
OBJECT_EVENT_GRAPHICS_ID_OFFSET = 0x05
OBJECT_EVENT_MOVEMENT_TYPE_OFFSET = 0x06
OBJECT_EVENT_LOCAL_ID_OFFSET = 0x08
OBJECT_EVENT_MAP_NUM_OFFSET = 0x09
OBJECT_EVENT_MAP_GROUP_OFFSET = 0x0A
OBJECT_EVENT_ELEVATION_OFFSET = 0x0B
OBJECT_EVENT_X_OFFSET = 0x10
OBJECT_EVENT_Y_OFFSET = 0x12
OBJECT_EVENT_FACING_DIR_OFFSET = 0x18
OBJECT_EVENT_ACTIVE_BIT = 0
OBJECT_EVENT_OFFSCREEN_BIT = 14
OBJECT_EVENT_CURRENT_ELEVATION_MASK = 0x0F
OBJECT_EVENT_WANDERING_TYPES = {0x2, 0x3, 0x4, 0x5, 0x6}
OBJECT_EVENTS_PLAYER_INDEX = 0
MAP_OFFSET = 7  # Correction coords obj vs map

# Object Event Templates (default / saved NPC positions for current map)
OBJECT_EVENT_TEMPLATE_SIZE = 0x18
OBJECT_EVENT_TEMPLATE_LOCAL_ID_OFFSET = 0x00
OBJECT_EVENT_TEMPLATE_GRAPHICS_ID_OFFSET = 0x01
OBJECT_EVENT_TEMPLATE_X_OFFSET = 0x04
OBJECT_EVENT_TEMPLATE_Y_OFFSET = 0x06
OBJECT_EVENT_TEMPLATE_ELEVATION_OFFSET = 0x08
OBJECT_EVENT_TEMPLATE_MOVEMENT_TYPE_OFFSET = 0x09
OBJECT_EVENT_TEMPLATE_MOVEMENT_RANGE_OFFSET = 0x0A
OBJECT_EVENT_TEMPLATE_FLAG_ID_OFFSET = 0x14

# Map connections
MAP_CONNECTIONS_COUNT_OFFSET = 0x00
MAP_CONNECTIONS_CONNECTION_POINTER_OFFSET = 0x04
MAP_CONNECTION_SIZE = 0x0C
MAP_CONNECTION_DIRECTION_OFFSET = 0x00
MAP_CONNECTION_OFFSET_OFFSET = 0x04
MAP_CONNECTION_MAP_GROUP_OFFSET = 0x08
MAP_CONNECTION_MAP_NUM_OFFSET = 0x09

FACING_DIRECTION_MAP = {1: "down", 2: "up", 3: "left", 4: "right"}

# Party data
PARTY_BASE_ADDR = sym_addr("gPlayerParty")
POKEMON_DATA_SIZE = 100
PARTY_SIZE = 6
MAX_MON_MOVES = 4  # pokefirered/include/constants/global.h
PID_OFFSET = 0x00
OTID_OFFSET = 0x04
NICKNAME_OFFSET = 0x08
ENCRYPTED_BLOCK_OFFSET = 0x20
ENCRYPTED_BLOCK_SIZE = 48
SUBSTRUCTURE_SIZE = 12
STATUS_OFFSET = 0x50
LEVEL_OFFSET = 0x54
CURRENT_HP_OFFSET = 0x56
MAX_HP_OFFSET = 0x58
ATTACK_OFFSET = 0x5A
DEFENSE_OFFSET = 0x5C
SPEED_OFFSET = 0x5E
SP_ATTACK_OFFSET = 0x60
SP_DEFENSE_OFFSET = 0x62
SPECIES_NONE = 0

# PC storage (boxes + PC items)
GPOKEMON_STORAGE_PTR_ADDR = sym_addr("gPokemonStoragePtr")
POKEMON_STORAGE_CURRENT_BOX_OFFSET = 0x00
POKEMON_STORAGE_BOXES_OFFSET = 0x04  # alignment after u8 currentBox
TOTAL_BOXES_COUNT = 14
IN_BOX_COUNT = 30
BOX_POKEMON_SIZE = 80  # sizeof(struct BoxPokemon)
BOXMON_PID_OFFSET = 0x00
BOXMON_OTID_OFFSET = 0x04
BOXMON_NICKNAME_OFFSET = 0x08
BOXMON_FLAGS_OFFSET = 0x13  # isBadEgg/hasSpecies/isEgg/... bitfield
BOXMON_ENCRYPTED_BLOCK_OFFSET = 0x20
BOXMON_ENCRYPTED_BLOCK_SIZE = 48
PC_ITEMS_COUNT = 30  # pokefirered/include/constants/global.h
ITEM_SLOT_SIZE = 4  # struct ItemSlot: u16 itemId + u16 quantity

# Experience / stats constants (pokefirered/include/constants/pokemon.h)
MAX_LEVEL = 100
STAT_ATK = 1
STAT_DEF = 2
STAT_SPEED = 3
STAT_SPATK = 4
STAT_SPDEF = 5
SPECIES_SHEDINJA = 303

# Badges (FireRed): flags indices (bit offsets dans le blob flags)
#
# NOTE: We keep both a stable ID (used by the server for logs/progress) and a human label.
BADGES = [
    ("BOULDER", "Boulder Badge", 0x820),
    ("CASCADE", "Cascade Badge", 0x821),
    ("THUNDER", "Thunder Badge", 0x822),
    ("RAINBOW", "Rainbow Badge", 0x823),
    ("SOUL", "Soul Badge", 0x824),
    ("MARSH", "Marsh Badge", 0x825),
    ("VOLCANO", "Volcano Badge", 0x826),
    ("EARTH", "Earth Badge", 0x827),
]

# Types
POKEMON_TYPE_MAP = {
    255: "NONE",
    0: "NORMAL",
    1: "FIGHTING",
    2: "FLYING",
    3: "POISON",
    4: "GROUND",
    5: "ROCK",
    6: "BUG",
    7: "GHOST",
    8: "STEEL",
    9: "MYSTERY",
    10: "FIRE",
    11: "WATER",
    12: "GRASS",
    13: "ELECTRIC",
    14: "PSYCHIC",
    15: "ICE",
    16: "DRAGON",
    17: "DARK",
}

# Substructure order table (PID % 24)
SUBSTRUCTURE_ORDER = [
    "GAEM",
    "GAME",
    "GEAM",
    "GEMA",
    "GMAE",
    "GMEA",
    "AGEM",
    "AGME",
    "AEGM",
    "AEMG",
    "AMGE",
    "AMEG",
    "EGAM",
    "EGMA",
    "EAGM",
    "EAMG",
    "EMGA",
    "EMAG",
    "MGAE",
    "MGEA",
    "MAGE",
    "MAEG",
    "MEGA",
    "MEAG",
]

# Status condition masks
STATUS_CONDITION_MASKS = [
    (0b111, "SLEEP"),
    (1 << 3, "POISON"),
    (1 << 4, "BURN"),
    (1 << 5, "FREEZE"),
    (1 << 6, "PARALYSIS"),
    (1 << 7, "BAD_POISON"),
]

# =============================================================================
