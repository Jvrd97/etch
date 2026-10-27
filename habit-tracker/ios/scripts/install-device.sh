#!/usr/bin/env bash
# [review:need-review] PHASE-01/208
# summary: build the iOS app with automatic signing (personal team from project.yml) and install it on a paired iPhone via devicectl; names the step it stopped at
set -euo pipefail

IOS_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PROJECT_DIR="$IOS_DIR/HabitTracker"
CONFIGURATION="${IOS_CONFIGURATION:-Debug}"
DERIVED_DATA="${IOS_DERIVED_DATA:-$PROJECT_DIR/DerivedData/device}"
DEVICE="${IOS_DEVICE:-}"
# The default bundle id may already be taken on Apple's side; Xcode then refuses to
# register it for the team, and a personal id (com.<name>.habittracker) fixes that.
BUNDLE_ID="${IOS_BUNDLE_ID:-}"
APP_PATH="$DERIVED_DATA/Build/Products/$CONFIGURATION-iphoneos/HabitTracker.app"

STEP=""
step() {
    STEP="$1"
    printf '\n==> %s\n' "$STEP"
}
stop() {
    printf '\nОстановлено на шаге «%s»: %s\n' "$STEP" "$1" >&2
    exit 1
}

# Prints "identifier<TAB>udid<TAB>tunnel state<TAB>developer mode" for the iOS device
# whose name, CoreDevice identifier or UDID equals $1; with no match prints nothing.
# With $1 empty lists every paired iOS device instead.
describe_devices() {
    local json
    json="$(mktemp)"
    xcrun devicectl list devices --json-output "$json" >/dev/null 2>&1 || true
    /usr/bin/python3 -I - "$json" "$1" <<'PY'
import json, sys
path, wanted = sys.argv[1], sys.argv[2]
try:
    devices = json.load(open(path))["result"]["devices"]
except (OSError, ValueError, KeyError):
    devices = []
for d in devices:
    hw, props, conn = d["hardwareProperties"], d["deviceProperties"], d["connectionProperties"]
    if hw.get("platform") != "iOS":
        continue
    row = [d["identifier"], hw.get("udid", ""), conn.get("tunnelState", ""), props.get("developerModeStatus", "")]
    if not wanted:
        print(f'  {props.get("name", "?")}  id={d["identifier"]}  state={row[2]}  developer mode={row[3]}')
    elif wanted in (props.get("name"), d["identifier"], hw.get("udid")):
        print("\t".join(row))
        break
PY
    rm -f "$json"
}

step "xcodegen generate"
command -v xcodegen >/dev/null || stop "нет xcodegen, поставь: brew install xcodegen"
(cd "$PROJECT_DIR" && xcodegen generate --quiet) || stop "xcodegen не собрал проект из project.yml"

step "поиск телефона"
if [ -z "$DEVICE" ]; then
    echo "Сопряжённые iOS-устройства:"
    describe_devices ""
    stop "укажи свой телефон: IOS_DEVICE=<id из списка> make ios-device"
fi
INFO="$(describe_devices "$DEVICE")"
[ -n "$INFO" ] || stop "устройство «$DEVICE» не найдено среди сопряжённых (xcrun devicectl list devices)"
IFS=$'\t' read -r DEVICE_ID DEVICE_UDID TUNNEL DEV_MODE <<<"$INFO"
[ "$TUNNEL" != "unavailable" ] || stop "телефон недоступен: разблокируй его и подключи кабелем или к той же сети Wi-Fi, что и Mac"
[ "$DEV_MODE" = "enabled" ] || stop "на телефоне выключен Developer Mode: Настройки → Конфиденциальность и безопасность → Режим разработчика"

step "сборка и подпись (xcodebuild)"
BUILD_SETTINGS=()
[ -z "$BUNDLE_ID" ] || BUILD_SETTINGS+=("PRODUCT_BUNDLE_IDENTIFIER=$BUNDLE_ID")
xcodebuild build \
    -project "$PROJECT_DIR/HabitTracker.xcodeproj" \
    -scheme HabitTracker \
    -configuration "$CONFIGURATION" \
    -destination "platform=iOS,id=$DEVICE_UDID" \
    -derivedDataPath "$DERIVED_DATA" \
    -allowProvisioningUpdates \
    -allowProvisioningDeviceRegistration \
    -quiet \
    ${BUILD_SETTINGS[@]+"${BUILD_SETTINGS[@]}"} \
    || stop "xcodebuild не собрал или не подписал приложение; «No Account for Team» — войди в Xcode → Settings → Accounts под командой из project.yml"

step "установка на телефон (devicectl)"
xcrun devicectl device install app --device "$DEVICE_ID" "$APP_PATH" \
    || stop "devicectl не установил приложение; если телефон спросил о доверии — подтверди разработчика в Настройки → Основные → VPN и управление устройством"

printf '\nГотово: HabitTracker установлен на «%s». Запуск: xcrun devicectl device process launch --device %s %s\n' \
    "$DEVICE" "$DEVICE_ID" "${BUNDLE_ID:-com.daniilbystrov.habittracker.HabitTracker}"
