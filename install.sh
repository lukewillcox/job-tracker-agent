#!/usr/bin/env bash
# Job Tracker installer, the fun way.
#   curl -fsSL https://raw.githubusercontent.com/lukewillcox/job-tracker-agent/main/install.sh | bash
#
# Asks the important questions, installs `jobtracker` with uv, then runs `jobtracker setup --username <name>`.
# Assumes the CLI package lives in ./cli of this repo (Kiro milestone: local CLI).
# Preview without installing anything:  JOBTRACKER_DRY_RUN=1 bash install.sh
set -euo pipefail

REPO="https://github.com/lukewillcox/job-tracker-agent"
PKG_SPEC="git+${REPO}#subdirectory=cli"
DRY="${JOBTRACKER_DRY_RUN:-0}"

# ---------- colours (switch off with NO_COLOR=1 or when not a terminal) ----------
if [[ -t 1 && -z "${NO_COLOR:-}" ]]; then
  P=$'\033[35m'; G=$'\033[32m'; Y=$'\033[33m'; R=$'\033[31m'; B=$'\033[1m'; D=$'\033[2m'; N=$'\033[0m'
else
  P=""; G=""; Y=""; R=""; B=""; D=""; N=""
fi

say()  { printf "%s\n" "$*"; }
ok()   { printf "  ${G}✓${N} %s\n" "$*"; }
warn() { printf "  ${Y}!${N} %s\n" "$*"; }
die()  { printf "\n  ${R}✗ %s${N}\n\n" "$*"; exit 1; }
pause(){ [[ "$DRY" == "1" ]] || sleep "${1:-0.4}"; }

# Spinner with a joke while a command runs
spin() {
  local msg="$1"; shift
  if [[ "$DRY" == "1" ]]; then ok "$msg ${D}(dry run)${N}"; return 0; fi
  "$@" >/tmp/jobtracker-install.log 2>&1 &
  local pid=$! frames='⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏' i=0
  while kill -0 "$pid" 2>/dev/null; do
    printf "\r  ${P}%s${N} %s" "${frames:i++%${#frames}:1}" "$msg"; sleep 0.1
  done
  if wait "$pid"; then printf "\r  ${G}✓${N} %s\n" "$msg"
  else printf "\r  ${R}✗${N} %s\n" "$msg"; die "Something broke. Details: /tmp/jobtracker-install.log"; fi
}

# ---------- the show ----------
clear 2>/dev/null || true
cat <<ART
${P}${B}
     _       _       _____               _
    | | ___ | |__   |_   _| __ __ _  ___| | _____ _ __
 _  | |/ _ \\| '_ \\    | || '__/ _\` |/ __| |/ / _ \\ '__|
| |_| | (_) | |_) |   | || | | (_| | (__|   <  __/ |
 \\___/ \\___/|_.__/    |_||_|  \\__,_|\\___|_|\\_\\___|_|
${N}
${D}   because "we'll keep your CV on file" is not a status update${N}

ART
pause 0.8

# ---------- the interview ----------
TTY=/dev/tty
ask() {  # ask "prompt" default -> echoes answer (default used in dry run / no terminal)
  local prompt="$1" def="${2:-}" ans=""
  if ! { : <"$TTY"; } 2>/dev/null; then   # no terminal to ask: use the default
    printf "%s%s\n" "$prompt" "$def" >&2; printf "%s" "$def"; return
  fi
  read -r -p "$prompt" ans <"$TTY" || true
  printf "%s" "$ans"
}
yes_or_bye() {  # yes_or_bye "question" "goodbye message"
  local a; a="$(ask "  $1 ${B}[y/n]${N} " y)"
  [[ "$a" =~ ^[Yy] ]] || die "$2"
}

say "  ${B}Aghhhhhh, so you want to use Daddy Winky's agent.${N}"
say "  Well, aren't you such a good boy for applying to them jobs."
say ""
yes_or_bye "If you're a good boy press y to continue, n not to." \
  "Not a good boy. Come back when you've sent some applications."
say ""

# The username Luke created with `jt-admin add`. Accept a-z 0-9 - _, lowercase,
# and normalise _ -> - so it matches jt-admin (which stores hyphens).
while :; do
  RAW_USERNAME="$(ask "  The username Luke gave you (a-z, 0-9, - or _): " "${JOBTRACKER_USERNAME:-test-luke}")"
  JT_USERNAME="$(printf '%s' "$RAW_USERNAME" | tr '[:upper:]' '[:lower:]' | tr '_' '-')"
  [[ "$JT_USERNAME" =~ ^[a-z0-9-]{2,30}$ ]] && break
  warn "Use letters, numbers, - or _ (what Luke sent you). Try again."
done
[[ "$JT_USERNAME" != "$(printf '%s' "$RAW_USERNAME" | tr '[:upper:]' '[:lower:]')" ]] \
  && say "  ${D}(normalised to '${JT_USERNAME}')${N}"
ok "Welcome, ${B}${JT_USERNAME}${N}."
say ""

yes_or_bye "Are you Luigi's little Mario?" \
  "No Mario, no tracker. Those are the rules."
ok "Wahoo."
say ""

say "  ${B}🍺 The bill${N}"
cat <<COST
  Every scan uses Luke's AI credits. It costs pennies, but Luke keeps a tab
  and it's measured in ${B}beers${N} (1 beer = £6).
  A scan is usually a tiny fraction of a beer. Run ${B}jobtracker status${N}
  anytime to see how many you owe him. Payment accepted at the pub.

COST
pause 0.6

tries=0
until [[ "$(ask "  Final question. Who's ya daddy? " Luke | tr '[:upper:]' '[:lower:]' | xargs)" == "luke" ]]; do
  tries=$((tries+1))
  (( tries >= 3 )) && die "Wrong. Three times. Installation denied."
  warn "Wrong answer. Think harder."
done
ok "Correct. Installing..."
say ""
pause 0.6

QUIPS=(
  "Counting how many times you've written 'I'm passionate about markets'..."
  "Teaching the robot the difference between 'unfortunately' and 'unfortunately, we'd love to invite you'..."
  "Preparing emotional support for HireVue..."
  "Converting 'we'll be in touch' into 'Awaiting response'..."
  "Calculating days since Citi last texted back..."
  "Practising mental maths: 80 questions in 8 minutes, no pressure..."
)
pick() { printf "%s" "${QUIPS[RANDOM % ${#QUIPS[@]}]}"; }

say "${B}Step 1/4 · Checking your machine${N}"
pause
[[ "$(uname -s)" == "Darwin" ]] && ok "macOS detected. Very finance of you." \
  || warn "Not macOS. It should work, but the scheduler is Mac-only for now."
command -v python3 >/dev/null && ok "Python found ($(python3 --version 2>&1 | cut -d' ' -f2))" \
  || warn "No Python, no problem: uv will fetch one."
command -v git >/dev/null && ok "git found" || die "git is missing. Run: xcode-select --install, then try again."
pause

say ""
say "${B}Step 2/4 · Getting uv (the thing that installs things)${N}"
if command -v uv >/dev/null; then
  ok "uv already installed. Look at you, prepared."
else
  say "  uv isn't installed. It's a fast Python installer from Astral."
  if [[ "$DRY" != "1" ]]; then
    ans="$(ask "  Install it now? [Y/n] " y)"
    [[ "${ans:-y}" =~ ^[Nn] ]] && die "No uv, no tracker. Install it from https://docs.astral.sh/uv/ and rerun."
  fi
  spin "Installing uv. $(pick)" sh -c 'curl -LsSf https://astral.sh/uv/install.sh | sh'
  export PATH="$HOME/.local/bin:$PATH"
fi

say ""
say "${B}Step 3/4 · Installing jobtracker${N}"
spin "$(pick)" uv tool install --force "$PKG_SPEC"
spin "$(pick)" sleep 1
ok "jobtracker installed. It reads your email ${B}read-only${N}, on ${B}your${N} laptop."

say ""
say "${B}Step 4/4 · Setup${N}"
cat <<NOTE
  Next you'll:
   1. paste the ${B}invite code${N} Luke sent you
   2. sign in to Microsoft in your browser (read-only mail access)
   3. build your ${B}job search profile${N}: drag in your CV and/or say in a
      sentence what you're after, and it finds new roles for you every week
   4. watch your first scan fill in the tracker

  ${D}Heads-up: Microsoft will say the app is "unverified". That's Luke, not a hacker.${N}

NOTE
pause 0.6

if [[ "$DRY" == "1" ]]; then
  ok "Dry run finished. Nothing was installed."
  exit 0
fi

if command -v jobtracker >/dev/null; then
  jobtracker setup --username "$JT_USERNAME" </dev/tty
else
  warn "Open a new terminal window and run: jobtracker setup"
fi

cat <<BYE

${G}${B}  You're in. May your inbox be full of "Congratulations!" 🎉${N}
${D}  Commands: jobtracker scan · jobtracker prospects · jobtracker profile · jobtracker status${N}
${D}  Your tracker: ~/.jobtracker/Job_Applications_Tracker.xlsx${N}

BYE
