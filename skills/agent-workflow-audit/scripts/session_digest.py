#!/usr/bin/env python3
"""Turn a repo's past AI coding-agent sessions into a small, deterministic digest.

Reads Claude Code transcripts, Codex rollouts, the OpenCode database, Pi session
files and the T3 Code database (all read-only), plus sessions converted to the
`format` JSONL by hand, keeps the sessions that belong to one git repo, and writes:

  summary.md            sources, headline metrics, tables across sessions
  prompts.md            recurring phrases, then every human prompt by session
  sessions/<id>.md      one digest per session
  scan.json             machine-readable index used by `show` and `compare`

Subcommands:
  scan     build the digest
  show     print a compact, numbered trace of one session (evidence lookup)
  compare  before/after table of headline metrics from two scan.json files
  count    count a regex across a scan's prompts, calls or results (by week/tool/model)
  format   print the JSONL format that `scan --import` reads

Each store is one Adapter subclass (see ADAPTERS); adding a harness is one class
plus a parse function registered in parse_native().

Standard library only, Python 3.9+.
"""

import argparse
import collections
import datetime
import glob
import gzip
import hashlib
import json
import os
import re
import shlex
import sqlite3
import statistics
import subprocess
import sys
import time

VERSION = 1
HOME = os.path.expanduser("~")
CLAUDE_HOME = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(HOME, ".claude")
CODEX_HOME = os.environ.get("CODEX_HOME") or os.path.join(HOME, ".codex")
T3_HOME = os.environ.get("T3_HOME") or os.path.join(HOME, ".t3")
_XDG_DATA = os.environ.get("XDG_DATA_HOME") or os.path.join(HOME, ".local", "share")
OPENCODE_DB = os.environ.get("OPENCODE_DB") or os.path.join(_XDG_DATA, "opencode", "opencode.db")
PI_SESSIONS = os.environ.get("PI_SESSIONS_DIR") or os.path.join(os.environ.get("PI_CODING_AGENT_DIR") or os.path.join(HOME, ".pi", "agent"), "sessions")

KEEP_TEXT = 4000          # chars of prompt / assistant text kept per item
KEEP_RESULT = 1200        # chars of tool result kept per item
IDLE_BEFORE_PROMPT = 60   # seconds; longer gaps that end at a human prompt are idle
GENERIC_NAMES = {
    "app", "apps", "web", "src", "repo", "repos", "project", "projects", "test", "tests",
    "api", "server", "client", "frontend", "backend", "main", "master", "code", "work",
    "dev", "tmp", "temp", "demo", "site", "docs", "lib", "core", "home", "worktrees",
}

# --------------------------------------------------------------------------
# small helpers


def parse_ts(v):
    """ISO-8601 string (with Z or offset), epoch seconds or epoch ms -> float epoch seconds."""
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        x = float(v)
        return x / 1000.0 if x > 1e11 else x
    s = str(v).strip()
    m = re.match(r"^(\d{4})-(\d\d)-(\d\d)[T ](\d\d):(\d\d):(\d\d)(\.\d+)?(Z|[+-]\d\d:?\d\d)?$", s)
    if not m:
        if re.match(r"^\d+(\.\d+)?$", s):
            return parse_ts(float(s))
        return None
    y, mo, d, h, mi, se = (int(m.group(i)) for i in range(1, 7))
    frac = float(m.group(7)) if m.group(7) else 0.0
    dt = datetime.datetime(y, mo, d, h, mi, se, tzinfo=datetime.timezone.utc)
    off = m.group(8)
    secs = dt.timestamp() + frac
    if off and off != "Z":
        sign = 1 if off[0] == "+" else -1
        hh, mm = int(off[1:3]), int(off[-2:])
        secs -= sign * (hh * 3600 + mm * 60)
    return secs


def fmt_ts(t):
    if t is None:
        return "?"
    return datetime.datetime.fromtimestamp(t, datetime.timezone.utc).strftime("%Y-%m-%d %H:%MZ")


def fmt_date(t):
    if t is None:
        return "?"
    return datetime.datetime.fromtimestamp(t, datetime.timezone.utc).strftime("%Y-%m-%d")


def fmt_dur(s):
    if s is None:
        return "?"
    s = int(round(s))
    if s < 60:
        return "%ds" % s
    if s < 3600:
        return "%dm" % (s // 60)
    return "%dh%02dm" % (s // 3600, (s % 3600) // 60)


def fmt_n(n):
    if n is None:
        return "?"
    n = float(n)
    for unit, div in (("B", 1e9), ("M", 1e6), ("k", 1e3)):
        if abs(n) >= div:
            return ("%.1f" % (n / div)).rstrip("0").rstrip(".") + unit
    return str(int(round(n)))


def ptext(kind, text):
    """Human prompts keep their full text (count matches on it); other kinds keep head and tail."""
    return redact(text or "") if kind == "human" else keep(text)


def keep(s, n=None):
    """Keep head and tail of long text (the tail holds 'done' claims and final answers)."""
    n = n or KEEP_TEXT
    s = s or ""
    if len(s) <= n:
        return redact(s)
    m = 300  # margin so a secret on the cut still matches its pattern
    return redact(s[: n // 2 + m])[: n // 2] + " … " + redact(s[-(n // 2) - m:])[-(n // 2):]


def one_line(s):
    return re.sub(r"\s+", " ", (s or "").replace("\r", "")).strip()


def flat(s):
    """Keep line structure visible on one line."""
    s = (s or "").replace("\r", "")
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n\s*\n+", "\n", s.strip())
    return s.replace("\n", " ⏎ ")


def head(s, n):
    s = s or ""
    return s if len(s) <= n else s[: max(0, n - 1)] + "…"


def tail(s, n):
    s = s or ""
    return s if len(s) <= n else "…" + s[-(n - 1):]


def md_cell(s):
    return (s or "").replace("|", "\\|").replace("\n", " ")


def median(xs):
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else None


def sha(s):
    return hashlib.sha1(s.encode("utf-8", "replace")).hexdigest()


def text_of(content):
    """Text from a tool-result / message content that may be str, list of blocks or dict."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for b in content:
            if isinstance(b, dict):
                if "text" in b and isinstance(b["text"], str):
                    parts.append(b["text"])
                elif b.get("type") == "image":
                    parts.append("[image]")
                elif "content" in b:
                    parts.append(text_of(b["content"]))
            elif isinstance(b, str):
                parts.append(b)
        return "\n".join(parts)
    if isinstance(content, dict):
        if "text" in content and isinstance(content["text"], str):
            return content["text"]
        return json.dumps(content, ensure_ascii=False, sort_keys=True)
    return str(content)


def norm_path(p):
    if not p:
        return ""
    if p.startswith("file://"):
        p = p[7:]
    p = os.path.normpath(os.path.expanduser(p))
    return p.rstrip("/") or "/"


def under(path, roots):
    """True when path equals or sits below one of roots (separator boundary)."""
    if not path:
        return None
    for r in roots:
        if path == r or path.startswith(r + "/"):
            return r
    return None


def norm_remote(url):
    if not url:
        return ""
    u = url.strip()
    u = re.sub(r"^[a-z+]+://", "", u)
    u = re.sub(r"^[^@/]+@", "", u)          # user@ or git@
    u = re.sub(r"^([^/:]+):(?!\d+/)", r"\1/", u)  # scp form host:owner/repo
    u = re.sub(r":\d+/", "/", u)            # explicit port
    u = u.rstrip("/")
    if u.endswith(".git"):
        u = u[:-4]
    return u.lower()


# --------------------------------------------------------------------------
# redaction (single choke point: every byte written or printed goes through it)

_REDACT = [
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(-----END [A-Z ]*PRIVATE KEY-----|$)", re.S), None),
    (re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}"), None),
    (re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"), None),
    (re.compile(r"github_pat_[A-Za-z0-9_]{20,}"), None),
    (re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"), None),
    (re.compile(r"xox[abposr]-[A-Za-z0-9\-]{10,}"), None),
    # JWTs, also when a truncated result cut the payload or signature off
    (re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}(?:\.[A-Za-z0-9_\-]*){0,2}"), None),
    # HTTP headers: Cookie, Set-Cookie, Authorization (any scheme)
    (re.compile(r"(?i)\b((?:set-)?cookie\\?[\"']?\s*:\s*\\?[\"']?)[^\s\"'\\][^\n\"\\]{7,}"), 1),
    (re.compile(r"(?i)\b(authorization\\?[\"']?\s*[:=]\s*\\?[\"']?(?:(?:basic|bearer|token|digest)\s+)?)[A-Za-z0-9._~+/=\-]{12,}"), 1),
    (re.compile(r"(?i)\b(bearer\s+)[A-Za-z0-9._~+/=\-]{12,}"), 1),
    # env forms: FOO_TOKEN=..., API_KEY=..., DB_PASSWORD="..."
    (re.compile(r"\b([A-Z0-9_]*(?:TOKEN|SECRET|PASSWORD|PASSWD|API_KEY|APIKEY|ACCESS_KEY)[A-Z0-9_]*\s*=\s*\\?[\"']?)[^\s\"'\\]{3,}"), 1),
    # key=value, key: value and JSON forms (also with escaped quotes inside JSON strings)
    (re.compile(r"(?i)(\b(?:password|passwd|pwd|token|(?:access|refresh|auth|id|session|bearer|csrf)[_-]?token|secret|client[_-]?secret|api[_-]?key|private[_-]?key)\\?[\"']?\s*[:=]\s*\\?[\"']?)(?!\[redacted\])[^\s\"'\\,;&}{)\]]{3,}"), 1),
    (re.compile(r"\b(?!git@)[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}\b"), None),
]


def redact(s):
    if not s:
        return s
    for rx, keep in _REDACT:
        if keep:
            s = rx.sub(lambda m: m.group(1) + "[redacted]", s)
        else:
            s = rx.sub("[redacted]", s)
    return s


def redact_obj(o):
    """Redact every string inside a JSON-able value (redacting serialised JSON can break escapes)."""
    if isinstance(o, str):
        return redact(o)
    if isinstance(o, dict):
        return collections.OrderedDict((k, redact_obj(v)) for k, v in o.items())
    if isinstance(o, (list, tuple)):
        return [redact_obj(v) for v in o]
    return o


def write_file(path, text, raw=False):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text if raw else redact(text))


def out(s=""):
    sys.stdout.write(redact(s) + "\n")


# --------------------------------------------------------------------------
# shell command handling

SUBCMD_PROGS = {
    "git", "gh", "pnpm", "npm", "yarn", "npx", "bun", "bunx", "vp", "cargo", "go", "docker",
    "kubectl", "make", "uv", "pip", "pip3", "poetry", "dotnet", "wrangler", "turbo", "nx",
    "deno", "mvn", "gradle", "terraform", "systemctl", "brew", "apt", "apt-get", "pacman",
    "yay", "rustup", "flutter", "dart", "composer", "bundle", "rails", "mix", "helm", "aws",
    "gcloud", "az", "firebase", "vercel", "netlify", "supabase", "prisma", "playwright",
    "vitest", "corepack", "pnpx", "just", "task", "tsx", "jest", "biome", "oxlint",
}
INTERPRETERS = {"python", "python3", "node", "ruby", "perl", "php", "bash", "sh", "zsh"}
VALUED_FLAGS = {"-C", "--filter", "-F", "--dir", "--prefix", "-w", "--workspace", "--cwd",
                "-R", "--repo", "-p", "--project", "--manifest-path", "-f", "--file"}
WRAPPERS = {"sudo", "time", "nice", "command", "exec", "nohup", "env", "stdbuf", "xargs"}
READ_PROGS = {"cat", "nl", "head", "tail", "bat", "less", "more"}


def unwrap_shell(cmd):
    """Return the inner script of `bash -lc '...'` wrappers (argv list or string)."""
    if cmd is None:
        return ""
    if isinstance(cmd, list):
        if len(cmd) >= 3 and os.path.basename(str(cmd[0])) in ("bash", "sh", "zsh") and str(cmd[1]) in ("-lc", "-c", "-ic"):
            return str(cmd[2])
        return " ".join(shlex.quote(str(c)) for c in cmd)
    s = str(cmd).strip()
    m = re.match(r"^(?:/usr/bin/|/bin/|/usr/local/bin/)?(?:ba|z)?sh\s+-[il]?c\s+(.*)$", s, re.S)
    if m:
        rest = m.group(1).strip()
        try:
            parts = shlex.split(rest)
            if parts:
                return parts[0]
        except ValueError:
            pass
        if len(rest) >= 2 and rest[0] == rest[-1] and rest[0] in "'\"":
            return rest[1:-1]
        return rest
    return s


_HEREDOC = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")


def strip_heredocs(script):
    """Remove heredoc bodies so their lines are not taken for commands."""
    out_, lines, i = [], script.split("\n"), 0
    while i < len(lines):
        line = lines[i]
        out_.append(line)
        tags = [m.group(2) for m in _HEREDOC.finditer(line)]
        i += 1
        for tag in tags:
            while i < len(lines) and lines[i].strip() != tag:
                i += 1
            i += 1
    return "\n".join(out_)


def split_segments(script):
    # rough split on control operators outside quotes
    script = strip_heredocs(script)
    segs, cur, q = [], [], None
    i, n = 0, len(script)
    while i < n:
        c = script[i]
        if q:
            cur.append(c)
            if c == q:
                q = None
            elif c == "\\" and q == '"' and i + 1 < n:
                cur.append(script[i + 1])
                i += 1
        elif c in "'\"":
            q = c
            cur.append(c)
        elif c == "&" and ((i > 0 and script[i - 1] in "<>") or (i + 1 < n and script[i + 1] == ">")):
            cur.append(c)  # redirection such as 2>&1 or &>file, not a separator
        elif c == "|" and i > 0 and script[i - 1] == ">":
            cur.append(c)  # >| clobber redirection
        elif c in ";\n|&":
            segs.append("".join(cur))
            cur = []
            while i + 1 < n and script[i + 1] in ";|&":
                i += 1
        else:
            cur.append(c)
        i += 1
    segs.append("".join(cur))
    return [s.strip() for s in segs if s.strip()]


def _tokens(seg):
    try:
        return shlex.split(seg)
    except ValueError:
        return seg.split()


def _strip_prefix(toks):
    i = 0
    while i < len(toks):
        t = toks[i]
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", t):
            i += 1
            continue
        if t == "timeout":
            i += 1
            while i < len(toks) and (toks[i].startswith("-") or re.match(r"^\d+(\.\d+)?[smhd]?$", toks[i])):
                if toks[i] in ("-s", "-k", "--signal", "--kill-after"):
                    i += 1
                i += 1
            continue
        if t in WRAPPERS:
            i += 1
            while i < len(toks) and toks[i].startswith("-"):
                i += 1
            continue
        break
    return toks[i:]


def _is_word(t):
    return bool(re.match(r"^[A-Za-z][A-Za-z0-9:_\-]*$", t))


def normalize_command(cmd):
    """`cd x && FOO=1 timeout 60 pnpm --filter web test -- a.ts` -> `pnpm test`."""
    script = unwrap_shell(cmd)
    for seg in split_segments(script):
        toks = _strip_prefix(_tokens(seg))
        if not toks:
            continue
        prog = os.path.basename(toks[0])
        if prog in ("cd", "pushd", "popd", "export", "set", "source", ".", "unset", "trap", "true", "echo") and len(split_segments(script)) > 1:
            continue
        if prog in ("for", "while", "until", "if"):
            return prog + "-loop" if prog != "if" else "if-block"
        if prog in INTERPRETERS:
            rest = toks[1:]
            for j, t in enumerate(rest):
                if t == "-m" and j + 1 < len(rest):
                    return "%s -m %s" % (prog, rest[j + 1])
                if t in ("-c", "-e", "--eval"):
                    return "%s %s" % (prog, t)
                if t.startswith("-"):
                    continue
                if t.startswith("<<") or t == "-":
                    return prog + " (stdin)"
                return "%s %s" % (prog, os.path.basename(t))
            return prog
        if prog in SUBCMD_PROGS:
            words, j = [], 1
            while j < len(toks) and len(words) < 2:
                t = toks[j]
                if t == "--":
                    break
                if t.startswith("-"):
                    if t in VALUED_FLAGS and "=" not in t:
                        j += 1
                    j += 1
                    continue
                if not _is_word(t):
                    break
                words.append(t)
                j += 1
            return " ".join([prog] + words)
        return prog
    return head(one_line(script), 40) or "(empty)"


_NOT_PROGRAMS = ("cd", "pushd", "popd", "export", "set", "source", ".", "unset", "trap", "true", ":")


def command_programs(cmd):
    """Normalised form of every program a shell line runs, in order, without repeats."""
    res = []
    for seg in split_segments(unwrap_shell(cmd)):
        toks = _strip_prefix(_tokens(seg))
        if not toks or os.path.basename(toks[0]) in _NOT_PROGRAMS or toks[0] in ("then", "do", "done", "fi", "else", "esac"):
            continue
        n = normalize_command(seg)
        if n not in res:
            res.append(n)
    return res or [normalize_command(cmd)]


_EDIT_TOOLS = {"edit", "write", "multiedit", "notebookedit", "apply_patch", "file_change", "patch", "str_replace",
               "str_replace_editor", "create_file", "edit_file", "write_file", "replace", "insert"}
_MUTATING_PROGS = {"mv", "cp", "rm", "mkdir", "touch", "tee", "ln", "chmod", "patch", "apply_patch", "install", "rsync", "unzip", "tar"}
_MUTATING_SUB = {
    "git": {"add", "commit", "checkout", "switch", "stash", "pull", "merge", "rebase", "reset", "apply", "restore",
            "cherry-pick", "rm", "mv", "am", "revert", "clean"},
    "pnpm": {"install", "i", "add", "remove", "rm", "update", "up", "dedupe"},
    "npm": {"install", "i", "ci", "uninstall", "update"}, "yarn": {"install", "add", "remove", "upgrade"},
    "bun": {"install", "i", "add", "remove"}, "vp": {"install", "i", "add"}, "uv": {"add", "sync", "pip"},
    "pip": {"install", "uninstall"}, "pip3": {"install", "uninstall"}, "cargo": {"add", "update"},
}
_REDIRECT = re.compile(r"(?<![0-9&<>])>>?\s*(?!\s*/dev/null)(?!&)[^\s>&|;]")


def changes_state(call):
    """True when a call edits files or repo state, so an identical rerun after it is not blind."""
    tool = (call.get("tool") or "").split(".")[-1].split("__")[-1].lower()
    if tool in _EDIT_TOOLS:
        return True
    cmd = call.get("cmd")
    if not cmd:
        return False
    script = strip_heredocs(unwrap_shell(cmd))
    if _REDIRECT.search(script) or re.search(r"\b(sed|perl)\s+(-[a-zA-Z]*i|--in-place)", script):
        return True
    for seg in split_segments(script):
        toks = _strip_prefix(_tokens(seg))
        if not toks:
            continue
        prog = os.path.basename(toks[0])
        if prog in _MUTATING_PROGS:
            return True
        subs = _MUTATING_SUB.get(prog)
        if subs:
            words = [t for t in toks[1:] if not t.startswith("-")]
            if words and words[0] in subs:
                return True
    return False


def command_label(cmd):
    """Normalised form plus a marker when the shell line chains several programs."""
    n = normalize_command(cmd)
    segs = [x for x in split_segments(unwrap_shell(cmd)) if not re.match(r"^(cd|pushd|export|set|source)\b", x)]
    return n + (" (+%d chained)" % (len(segs) - 1) if len(segs) > 1 else "")


def files_read_by_command(cmd):
    script = unwrap_shell(cmd)
    files = []
    for seg in split_segments(script):
        toks = _strip_prefix(_tokens(seg))
        if not toks:
            continue
        prog = os.path.basename(toks[0])
        args = toks[1:]
        if prog == "sed":
            # sed -n '1,200p' file
            nonflag = [a for a in args if not a.startswith("-")]
            files.extend(nonflag[1:] if len(nonflag) > 1 else [])
        elif prog in READ_PROGS:
            skip = False
            for a in args:
                if skip:
                    skip = False
                    continue
                if a in ("-n", "-c"):
                    skip = True
                    continue
                if a.startswith("-") or a.startswith(">") or a.startswith("<"):
                    continue
                files.append(a)
    return [f for f in files if re.search(r"[/.]", f) and not f.startswith("$")]


# --------------------------------------------------------------------------
# human prompt classification

_INJECT = [
    re.compile(r"^<(task-notification|local-command-stdout|local-command-stderr|local-command-caveat|system-reminder|user-prompt-submit-hook|bash-stdout|bash-stderr|tool-use-id|teammate-message|channel-message|environment_context|user_instructions|turn_aborted|subagent_notification|recommended_plugins|skills_instructions|collaboration_mode|permissions)\b"),
    re.compile(r"^This session is being continued from a previous conversation"),
    re.compile(r"^Update on pull request #\d+ \("),
    re.compile(r"^Continue where you left off\. Your last turn was cut short"),
    re.compile(r"^Context handoff \("),
    re.compile(r"^Delegated task node:"),
    re.compile(r"^PR #\d+ \(https?://\S+\) conflicts with its base branch"),  # T3 "resolve conflicts" action
    re.compile(r"^Caveat: The messages below were generated by the user while running local commands"),
    re.compile(r"^\[Image: original \d+x\d+"),
    re.compile(r"^Your response above was stopped by a safety classifier"),
]
_AGENT_BRIEF = re.compile(r"^Act as the [\w-]+ sub-agent for this task")  # T3 delegate_task brief
_INTERRUPT = re.compile(r"^\[Request interrupted by user")
_HELPER = re.compile(
    r"^(You generate concise git branch names|You write concise git commit messages|"
    r"You write source control change request content|Generate a title that will help the user recognize)")
_CONTROL_COMMANDS = {"/compact", "/clear", "/model", "/cost", "/status", "/resume", "/exit", "/config", "/context", "/usage"}


_ATTACH = [
    (re.compile(r"<t3_context\b.*?</t3_context>", re.S), ""),
    (re.compile(r"\[Attached (image|file) \"([^\"\n]*)\" is saved at: [^\]\n]*\]"), r"[attached \1 \2]"),
    (re.compile(r"\[Image: ([^;\]\n]*); ref=[^\]\n]*\]"), r"[image \1]"),
    (re.compile(r"\[Image #\d+\]"), "[image]"),
    (re.compile(r"!\[([^\]\n]*)\]\((?:t3-context|attachment|file):[^)\s]*\)"), r"[image \1]"),
]


def clean_prompt(text):
    """Drop the attachment plumbing T3 appends to a typed prompt; keep a marker."""
    s = text or ""
    for rx, rep in _ATTACH:
        s = rx.sub(rep, s)
    return s.strip()


def classify_text(text):
    """-> (kind, text) with kind in human / inj / interrupt / control."""
    s = clean_prompt(text)
    if not s:
        return "inj", text
    if _INTERRUPT.match(s):
        return "interrupt", s
    m = re.match(r"^<command-(?:name|message)>", s)
    if m:
        name = re.search(r"<command-name>\s*(.*?)\s*</command-name>", s, re.S)
        args = re.search(r"<command-args>\s*(.*?)\s*</command-args>", s, re.S)
        name = (name.group(1) if name else "").strip()
        if not name.startswith("/") and name:
            name = "/" + name
        full = (name + " " + (args.group(1) if args else "")).strip()
        if name in _CONTROL_COMMANDS:
            return "control", full
        return "human", full or s
    if s.split(None, 1)[0] in _CONTROL_COMMANDS:
        return "control", s
    m = re.match(r"^<bash-input>(.*?)</bash-input>", s, re.S)
    if m:
        return "human", "!" + m.group(1).strip()
    for rx in _INJECT:
        if rx.match(s):
            return "inj", s
    if _AGENT_BRIEF.match(s):
        return "task", s
    return "human", s


def agent_key(text):
    return one_line(text)[:160]


# --------------------------------------------------------------------------
# normalised session items
#
# Every parser returns a list of dicts:
#   k     human | inj | task | interrupt | control | asst | call | res | compact | error
#   ts    epoch seconds or None
#   text  text (prompts, assistant text, result head, error text)
#   tool, inp (short input), key (repeat key), cmd (shell script), file (path read),
#   size (result chars), err (bool), dur (seconds), cid (call id), counted (bool)


def short_input(name, inp):
    if inp is None:
        return ""
    if isinstance(inp, str):
        return one_line(inp)
    if not isinstance(inp, dict):
        return one_line(json.dumps(inp, ensure_ascii=False))
    for k in ("command", "cmd", "file_path", "filePath", "path", "pattern", "query", "url", "description", "prompt", "skill"):
        v = inp.get(k)
        if isinstance(v, (str, list)) and v:
            v = unwrap_shell(v) if k in ("command", "cmd") else (v if isinstance(v, str) else " ".join(map(str, v)))
            extra = ""
            if k in ("file_path", "filePath", "path") and (inp.get("offset") or inp.get("limit")):
                extra = " [%s:%s]" % (inp.get("offset", ""), inp.get("limit", ""))
            return one_line(v) + extra
    return one_line(json.dumps(inp, ensure_ascii=False, sort_keys=True))


def call_key(tool, inp, cmd=None):
    if cmd:
        return "shell:" + sha(one_line(cmd))
    try:
        s = json.dumps(inp, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError):
        s = str(inp)
    return tool + ":" + sha(s)


def mk_call(ts, tool, inp, cid=None, cmd=None, file=None):
    return {"k": "call", "ts": ts, "tool": tool, "inp": redact(short_input(tool, inp) if not cmd else one_line(cmd)),
            "key": call_key(tool, inp, cmd), "cmd": cmd, "file": file, "cid": cid, "counted": True,
            "err": False, "dur": None, "res": None}


def mk_res(ts, call, text, err=False, size=None):
    t = text or ""
    r = {"k": "res", "ts": ts, "tool": call["tool"] if call else "?", "text": redact(t[:KEEP_RESULT + 300])[:KEEP_RESULT],
         "size": len(t) if size is None else size, "err": bool(err), "call": None}
    if call is not None:
        call["res"] = r
        call["err"] = bool(err) or call["err"]
        if call["ts"] is not None and ts is not None and call["dur"] is None:
            call["dur"] = max(0.0, ts - call["ts"])
        r["counted"] = call["counted"]
    else:
        r["counted"] = True
    return r


def new_meta():
    return {"tokens": {"in": 0, "cr": 0, "cw": 0, "out": 0}, "peak_ctx": None, "models": collections.Counter(),
            "cwd": None, "branch": None, "title": None, "cost": None, "start": None, "end": None,
            "bad_lines": 0, "compactions": 0, "session_id": None, "parent_native": None,
            "usage_records": 0, "usage_incomplete": 0, "remote": None, "entrypoint": None,
            "agent_type": None, "description": None, "spawned": 0, "notes": []}


def _touch(meta, ts):
    if ts is None:
        return
    if meta["start"] is None or ts < meta["start"]:
        meta["start"] = ts
    if meta["end"] is None or ts > meta["end"]:
        meta["end"] = ts


# ---------------------------------------------------------------- Claude Code

def claude_head(path, max_lines=300):
    """Cheap look at the first records: cwd, start, sessionId, entrypoint, first prompt."""
    info = {"cwd": None, "start": None, "session_id": None, "entrypoint": None, "first_prompt": None,
            "branch": None, "sidechain": False}
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for i, line in enumerate(f):
                if i >= max_lines:
                    break
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(d, dict):
                    continue
                if info["cwd"] is None and d.get("cwd"):
                    info["cwd"] = d.get("cwd")
                    info["branch"] = d.get("gitBranch")
                if info["start"] is None and d.get("timestamp"):
                    info["start"] = parse_ts(d.get("timestamp"))
                if info["session_id"] is None and d.get("sessionId"):
                    info["session_id"] = d.get("sessionId")
                if info["entrypoint"] is None and d.get("entrypoint"):
                    info["entrypoint"] = d.get("entrypoint")
                if d.get("isSidechain"):
                    info["sidechain"] = True
                if info["first_prompt"] is None and d.get("type") == "user" and not d.get("isMeta"):
                    c = (d.get("message") or {}).get("content")
                    if isinstance(c, str):
                        info["first_prompt"] = c[:300]
                if info["cwd"] and info["start"] and info["first_prompt"] is not None:
                    break
    except OSError:
        return None
    return info


def parse_claude(path, agent_texts=None, sidechain=False):
    items, meta = [], new_meta()
    usage = {}
    calls = {}
    agent_texts = agent_texts or set()
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                d = json.loads(line)
            except ValueError:
                meta["bad_lines"] += 1
                continue
            if not isinstance(d, dict):
                meta["bad_lines"] += 1
                continue
            t = d.get("type")
            ts = parse_ts(d.get("timestamp"))
            if t in ("user", "assistant", "system"):
                _touch(meta, ts)
                if meta["cwd"] is None and d.get("cwd"):
                    meta["cwd"] = d.get("cwd")
                if d.get("gitBranch"):
                    meta["branch"] = d.get("gitBranch")
                if meta["session_id"] is None and d.get("sessionId"):
                    meta["session_id"] = d.get("sessionId")
                if meta["entrypoint"] is None and d.get("entrypoint"):
                    meta["entrypoint"] = d.get("entrypoint")
            if t == "custom-title" and d.get("customTitle"):
                meta["title"] = d.get("customTitle")
            elif t in ("ai-title", "summary") and not meta["title"]:
                meta["title"] = d.get("title") or d.get("summary")
            elif t == "cost-state":
                if isinstance(d.get("totalCostUSD"), (int, float)):
                    # cumulative per process (startTime); sum the maxima in case of restarts
                    k = d.get("startTime")
                    costs = meta.setdefault("_costs", {})
                    costs[k] = max(costs.get(k, 0.0), float(d["totalCostUSD"]))
                    meta["cost"] = sum(costs.values())
            elif t == "system":
                if d.get("subtype") == "compact_boundary":
                    meta["compactions"] += 1
                    cm = d.get("compactMetadata") or {}
                    items.append({"k": "compact", "ts": ts, "text": "compaction (%s, %s tokens before)" % (cm.get("trigger", "?"), cm.get("preTokens", "?"))})
            elif t == "assistant":
                msg = d.get("message") or {}
                mid = msg.get("id") or d.get("uuid")
                u = msg.get("usage")
                if isinstance(u, dict):
                    prev = usage.get(mid)
                    if prev is None or (u.get("output_tokens") or 0) >= (prev.get("output_tokens") or 0):
                        usage[mid] = u
                model = msg.get("model")
                if model and model != "<synthetic>" and mid not in meta.get("_seen_model", set()):
                    meta.setdefault("_seen_model", set()).add(mid)
                    meta["models"][model] += 1
                for b in msg.get("content") or []:
                    if not isinstance(b, dict):
                        continue
                    bt = b.get("type")
                    if bt == "text" and (b.get("text") or "").strip():
                        txt = b["text"]
                        items.append({"k": "asst", "ts": ts, "text": keep(txt)})
                    elif bt == "tool_use":
                        name = b.get("name") or "?"
                        inp = b.get("input") or {}
                        cmd = inp.get("command") if name in ("Bash", "bash") and isinstance(inp, dict) else None
                        fpath = inp.get("file_path") if name == "Read" and isinstance(inp, dict) else None
                        c = mk_call(ts, name, inp, cid=b.get("id"), cmd=cmd, file=fpath)
                        if name in ("Agent", "Task"):
                            meta["spawned"] += 1
                        calls[b.get("id")] = c
                        items.append(c)
            elif t == "user":
                msg = d.get("message") or {}
                content = msg.get("content")
                is_meta = bool(d.get("isMeta"))
                if d.get("isCompactSummary"):
                    items.append({"k": "inj", "ts": ts, "text": keep(text_of(content)), "why": "compact summary"})
                    continue
                if isinstance(content, list):
                    texts = []
                    for b in content:
                        if not isinstance(b, dict):
                            continue
                        if b.get("type") == "tool_result":
                            c = calls.get(b.get("tool_use_id"))
                            rt = text_of(b.get("content"))
                            items.append(mk_res(ts, c, rt, err=b.get("is_error") is True))
                        elif b.get("type") == "text":
                            texts.append(b.get("text") or "")
                        elif b.get("type") == "image":
                            texts.append("[image]")
                    if texts:
                        txt = "\n".join(texts).strip()
                        _add_user_text(items, ts, txt, is_meta, sidechain, d, agent_texts)
                elif isinstance(content, str):
                    _add_user_text(items, ts, content, is_meta, sidechain, d, agent_texts)
    tok = meta["tokens"]
    peak = None
    for u in usage.values():
        i = int(u.get("input_tokens") or 0)
        cr = int(u.get("cache_read_input_tokens") or 0)
        cw = int(u.get("cache_creation_input_tokens") or 0)
        tok["in"] += i
        tok["cr"] += cr
        tok["cw"] += cw
        tok["out"] += int(u.get("output_tokens") or 0)
        ctx = i + cr + cw
        peak = ctx if peak is None or ctx > peak else peak
    meta["peak_ctx"] = peak
    meta["usage_records"] = len(usage)
    meta.pop("_seen_model", None)
    meta.pop("_costs", None)
    return items, meta


def _add_user_text(items, ts, txt, is_meta, sidechain, d, agent_texts):
    if not txt.strip():
        return
    if is_meta:
        items.append({"k": "inj", "ts": ts, "text": keep(txt), "why": "isMeta"})
        return
    if d.get("promptSource") == "system":
        items.append({"k": "inj", "ts": ts, "text": keep(txt), "why": "promptSource=system"})
        return
    kind, clean = classify_text(txt)
    if kind == "human" and sidechain:
        kind = "task"
    elif kind == "human" and agent_key(clean) in agent_texts:
        kind = "task"
    items.append({"k": kind, "ts": ts, "text": ptext(kind, clean)})


# ---------------------------------------------------------------- Codex

def codex_head(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for i, line in enumerate(f):
                if i > 20:
                    break
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                if isinstance(d, dict) and d.get("type") == "session_meta":
                    p = d.get("payload") or {}
                    git = p.get("git") or {}
                    return {"id": p.get("id"), "cwd": p.get("cwd"), "start": parse_ts(p.get("timestamp") or d.get("timestamp")),
                            "remote": git.get("repository_url"), "branch": git.get("branch"),
                            "parent": p.get("parent_thread_id"), "source": p.get("source")}
    except OSError:
        return None
    return None


def parse_codex(path, agent_texts=None):
    items, meta = [], new_meta()
    agent_texts = agent_texts or set()
    by_cid = {}
    open_exec = []
    seen_resp = set()
    last_thread_total = None
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                d = json.loads(line)
            except ValueError:
                meta["bad_lines"] += 1
                continue
            if not isinstance(d, dict):
                meta["bad_lines"] += 1
                continue
            t = d.get("type")
            p = d.get("payload") or {}
            if not isinstance(p, dict):
                continue
            ts = parse_ts(d.get("timestamp"))
            if t in ("response_item", "event_msg"):
                _touch(meta, ts)
            if t == "session_meta":
                meta["session_id"] = p.get("id")
                meta["cwd"] = p.get("cwd")
                git = p.get("git") or {}
                meta["branch"] = git.get("branch")
                meta["remote"] = git.get("repository_url")
                meta["parent_native"] = p.get("parent_thread_id")
                meta["agent_type"] = p.get("agent_nickname")
                _touch(meta, parse_ts(p.get("timestamp")))
            elif t == "turn_context":
                if p.get("model"):
                    meta["models"][p["model"]] += 1
            elif t == "token_usage_record":
                rid = p.get("response_id")
                if rid and rid in seen_resp:
                    continue
                if rid:
                    seen_resp.add(rid)
                u = p.get("usage") or {}
                inp = int(u.get("input_tokens") or 0)
                cached = int(u.get("cached_input_tokens") or 0)
                tok = meta["tokens"]
                tok["in"] += max(0, inp - cached)
                tok["cr"] += cached
                tok["cw"] += int(u.get("cache_write_input_tokens") or 0)
                tok["out"] += int(u.get("output_tokens") or 0)
                meta["usage_records"] += 1
                if meta["peak_ctx"] is None or inp > meta["peak_ctx"]:
                    meta["peak_ctx"] = inp
                if p.get("thread_token_usage"):
                    last_thread_total = p.get("thread_token_usage")
            elif t == "compacted":
                pass  # counted via the ContextCompaction item to avoid double counting
            elif t == "response_item":
                pt = p.get("type")
                if pt in ("function_call", "custom_tool_call"):
                    name = p.get("name") or "?"
                    raw = p.get("arguments") if pt == "function_call" else p.get("input")
                    inp = raw
                    if isinstance(raw, str) and pt == "function_call":
                        try:
                            inp = json.loads(raw)
                        except ValueError:
                            inp = raw
                    cmd = None
                    if name in ("exec_command", "shell", "local_shell") and isinstance(inp, dict):
                        cmd = unwrap_shell(inp.get("cmd") or inp.get("command"))
                    if pt == "custom_tool_call" and name == "exec":
                        c = mk_call(ts, "exec", {"script": head(raw if isinstance(raw, str) else "", 300)}, cid=p.get("call_id"))
                        c["key"] = call_key("exec", raw)
                        c["inner"] = []
                        open_exec.append(c)
                    else:
                        fl = files_read_by_command(cmd) if cmd else []
                        c = mk_call(ts, name, inp, cid=p.get("call_id"), cmd=cmd, file=fl[0] if fl else None)
                        c["files"] = fl
                    if name in ("spawn_agent",):
                        meta["spawned"] += 1
                    by_cid[p.get("call_id")] = c
                    items.append(c)
                elif pt in ("function_call_output", "custom_tool_call_output"):
                    c = by_cid.get(p.get("call_id"))
                    o = p.get("output")
                    otext = text_of(o) if not isinstance(o, str) else o
                    if c is not None and c.get("res") is not None:
                        c["res"]["size"] = len(otext)  # chars that entered the context
                        continue
                    err = False
                    m = re.search(r"Process exited with code (\d+)", otext[:400])
                    if m and m.group(1) != "0" and not (c is not None and c.get("tool") == "write_stdin"):
                        err = True
                    if otext.startswith("Script failed") or otext.startswith("unsupported custom tool"):
                        err = True
                    r = mk_res(ts, c, otext, err=err)
                    if c is not None and c.get("tool") == "exec":
                        if c in open_exec:
                            open_exec.remove(c)
                        inner = c.get("inner") or []
                        if inner:
                            # inner actions are the counted unit; the wrapper only counts as a
                            # failure when no inner action failed
                            c["counted"] = False
                            r["counted"] = False
                            if err and not any(x.get("err") for x in inner):
                                c["counted"] = True
                                r["counted"] = True
                                r["size"] = 0
                    items.append(r)
            elif t == "event_msg":
                pt = p.get("type")
                if pt == "item_completed":
                    it = p.get("item") or {}
                    if not isinstance(it, dict):
                        continue
                    _codex_item(items, meta, it, ts, by_cid, open_exec, agent_texts, p)
                elif pt == "turn_aborted":
                    items.append({"k": "interrupt", "ts": ts, "text": "turn aborted: %s" % p.get("reason", "?")})
                elif pt == "error":
                    items.append({"k": "error", "ts": ts, "text": one_line(str(p.get("message") or p))[:400]})
    if last_thread_total:
        tt = last_thread_total
        exp = (int(tt.get("input_tokens") or 0), int(tt.get("output_tokens") or 0))
        got = (meta["tokens"]["in"] + meta["tokens"]["cr"], meta["tokens"]["out"])
        if exp != got:
            meta["notes"].append("token sum differs from Codex running total (%s in / %s out recorded, %s / %s summed)" % (exp[0], exp[1], got[0], got[1]))
    return items, meta


def _codex_result(items, c, ts, text, err, size=None):
    if c.get("res") is not None:
        if err:
            c["err"] = c["res"]["err"] = True
        return
    items.append(mk_res(ts, c, text, err=err, size=size))


def _codex_item(items, meta, it, ts, by_cid, open_exec, agent_texts, p):
    ty = it.get("type")
    iid = it.get("id")
    st = parse_ts(p.get("started_at_ms"))
    en = parse_ts(p.get("completed_at_ms")) or ts
    if ty == "UserMessage":
        txt = text_of(it.get("content"))
        kind, clean = classify_text(txt)
        if kind == "human" and agent_key(clean) in agent_texts:
            kind = "task"
        items.append({"k": kind, "ts": en, "text": ptext(kind, clean)})
        return
    if ty == "AgentMessage":
        txt = text_of(it.get("content"))
        if txt.strip():
            items.append({"k": "asst", "ts": en, "text": keep(txt)})
        return
    if ty == "ContextCompaction":
        meta["compactions"] += 1
        items.append({"k": "compact", "ts": en, "text": "context compaction"})
        return
    if ty in ("Reasoning",):
        return
    if ty == "SubAgentActivity":
        return
    # actions
    parent_exec = open_exec[-1] if (open_exec and iid and str(iid).startswith("exec-")) else None
    existing = by_cid.get(iid)
    if ty == "CommandExecution":
        cmd = unwrap_shell(it.get("command"))
        dur = it.get("duration")
        secs = None
        if isinstance(dur, dict):
            secs = float(dur.get("secs") or 0) + float(dur.get("nanos") or 0) / 1e9
        output = it.get("aggregated_output")
        if output is None:
            output = (it.get("stdout") or "") + (it.get("stderr") or "")
        ec = it.get("exit_code")
        err = it.get("status") == "failed" or (ec not in (None, 0))
        fl = files_read_by_command(cmd)
        if existing is not None:
            c = existing
            c["cmd"] = cmd
            c["inp"] = redact(one_line(cmd))
            c["key"] = call_key("shell", None, cmd)
            c["files"] = fl
            c["file"] = fl[0] if fl else None
        else:
            c = mk_call(st or ts, "shell", None, cid=iid, cmd=cmd, file=fl[0] if fl else None)
            c["files"] = fl
            items.append(c)
        if secs is not None:
            c["dur"] = secs
        if c.get("res") is not None:
            # long-running command: its first output chunk came back earlier (and later chunks
            # through write_stdin); keep that position and size, record the final exit here
            r = c["res"]
            if err:
                r["err"] = c["err"] = True
                r["text"] = redact(("exit %s: " % ec) + (output or "")[:KEEP_RESULT + 300])[:KEEP_RESULT]
        else:
            r = mk_res(en, c, output or "", err=err)
            if ec not in (None, 0):
                r["text"] = ("exit %s: " % ec) + r["text"]
            items.append(r)
    elif ty == "McpToolCall":
        res = it.get("result") or {}
        rtext = text_of(res.get("content")) if isinstance(res, dict) else text_of(res)
        err = it.get("status") == "failed" or (isinstance(res, dict) and res.get("isError") is True) or bool(it.get("error"))
        if it.get("error") and not rtext:
            rtext = text_of(it.get("error"))
        name = "%s.%s" % (it.get("server") or "mcp", it.get("tool") or "?")
        if existing is not None:
            c = existing
        else:
            c = mk_call(st or ts, name, it.get("arguments"), cid=iid)
            items.append(c)
        _codex_result(items, c, en, rtext, err)
    elif ty == "FileChange":
        ch = it.get("changes") or {}
        files = sorted(ch.keys()) if isinstance(ch, dict) else []
        err = it.get("status") == "failed"
        if existing is not None:
            c = existing
        else:
            c = mk_call(st or ts, "apply_patch", {"files": files}, cid=iid)
            items.append(c)
        _codex_result(items, c, en, "edited: " + ", ".join(files[:5]), err, size=0)
    elif ty in ("WebSearch", "ImageView", "Extension"):
        inp = {"query": it.get("query")} if ty == "WebSearch" else ({"path": it.get("path")} if ty == "ImageView" else {"kind": it.get("kind")})
        name = {"WebSearch": "web_search", "ImageView": "view_image", "Extension": str(it.get("kind") or "extension")}[ty]
        if existing is not None:
            c = existing
        else:
            c = mk_call(st or ts, name, inp, cid=iid)
            items.append(c)
        _codex_result(items, c, en, "", it.get("status") == "failed", size=0)
    else:
        return
    if parent_exec is not None:
        parent_exec["inner"].append(c)


# ---------------------------------------------------------------- T3 Code

T3_REQUIRED = {
    "projection_projects": {"project_id", "workspace_root", "deleted_at"},
    "orchestration_v2_projection_threads": {"thread_id", "project_id", "title", "created_at", "payload_json"},
    "orchestration_v2_projection_provider_threads": {"thread_id", "provider", "payload_json"},
    "orchestration_v2_projection_turn_items": {"thread_id", "ordinal", "type", "status", "payload_json"},
    "orchestration_v2_projection_provider_turns": {"thread_id", "payload_json"},
}
T3_WORKTREE_EXPR = "CASE WHEN json_valid(payload_json) THEN json_extract(payload_json, '$.worktreePath') END"


def t3_connect(path):
    conn = sqlite3.connect("file:%s?mode=ro" % path, uri=True, timeout=10)
    conn.execute("PRAGMA query_only = 1")
    return conn


def t3_schema_problem(conn):
    have = {}
    for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table'"):
        have[name] = None
    missing = []
    for tbl, cols in sorted(T3_REQUIRED.items()):
        if tbl not in have:
            missing.append(tbl)
            continue
        got = {r[1] for r in conn.execute("PRAGMA table_info(%s)" % tbl)}
        lack = sorted(cols - got)
        if lack:
            missing.append("%s(%s)" % (tbl, ",".join(lack)))
    return missing


def _jl(s):
    try:
        v = json.loads(s) if s else {}
        return v if isinstance(v, dict) else {}
    except ValueError:
        return {}


def t3_thread_user_messages(conn, thread_id):
    rows = conn.execute(
        "SELECT payload_json FROM orchestration_v2_projection_turn_items WHERE thread_id = ? AND type = 'user_message' ORDER BY ordinal",
        (thread_id,)).fetchall()
    return [_jl(r[0]) for r in rows]


def t3_tokens(conn, thread_id, meta):
    rows = conn.execute(
        "SELECT payload_json FROM orchestration_v2_projection_provider_turns WHERE thread_id = ?", (thread_id,)).fetchall()
    tok = meta["tokens"]
    if not rows:
        meta["notes"].append("T3 recorded no provider turns, so no token usage")
    for (pj,) in rows:
        d = _jl(pj)
        tu = d.get("turnTokenUsage") or {}
        if d.get("model"):
            meta["models"][d["model"]] += 1
        elif tu.get("models"):
            for m in tu["models"]:
                meta["models"][m] += 1
        if not tu:
            meta["usage_incomplete"] += 1
            continue
        if tu.get("usageStatus") not in (None, "complete"):
            meta["usage_incomplete"] += 1
        inp = int(tu.get("inputTokens") or 0)
        cr = int(tu.get("cachedInputTokens") or 0)
        cw = int(tu.get("cacheCreationTokens") or 0)
        tok["in"] += max(0, inp - cr - cw)
        tok["cr"] += cr
        tok["cw"] += cw
        tok["out"] += int(tu.get("outputTokens") or 0)
        meta["usage_records"] += 1
        snap = d.get("tokenUsage") or {}
        if snap.get("usedTokens") and (meta["peak_ctx"] is None or snap["usedTokens"] > meta["peak_ctx"]):
            meta["peak_ctx"] = int(snap["usedTokens"])


def parse_t3(conn, thread_id):
    items, meta = [], new_meta()
    by_cid = {}
    rows = conn.execute(
        "SELECT ordinal, type, status, payload_json FROM orchestration_v2_projection_turn_items "
        "WHERE thread_id = ? AND type <> 'reasoning' ORDER BY ordinal, turn_item_id", (thread_id,)).fetchall()
    for ordinal, ty, status, pj in rows:
        d = _jl(pj)
        if not d:
            meta["bad_lines"] += 1
            continue
        st = parse_ts(d.get("startedAt"))
        en = parse_ts(d.get("completedAt")) or parse_ts(d.get("updatedAt")) or st
        _touch(meta, st)
        _touch(meta, en)
        failed = status == "failed"
        if ty == "user_message":
            txt = d.get("text") or ""
            if d.get("createdBy") == "user":
                kind, clean = classify_text(txt)
                items.append({"k": kind, "ts": st, "text": ptext(kind, clean)})
            else:
                items.append({"k": "task" if not txt.startswith("/") else "control", "ts": st, "text": keep(txt)})
        elif ty == "assistant_message":
            txt = d.get("text") or ""
            if txt.strip():
                items.append({"k": "asst", "ts": en, "text": keep(txt)})
        elif ty == "command_execution":
            inp = d.get("input")
            if d.get("title") == "Workspace ready" or inp == "Preparing workspace":
                continue
            cmd = unwrap_shell(inp)
            fl = files_read_by_command(cmd)
            c = mk_call(st, "shell", None, cid=d.get("id"), cmd=cmd, file=fl[0] if fl else None)
            c["files"] = fl
            items.append(c)
            ec = d.get("exitCode")
            r = mk_res(en, c, d.get("output") or "", err=failed or ec not in (None, 0))
            if ec not in (None, 0):
                r["text"] = ("exit %s: " % ec) + r["text"]
            items.append(r)
        elif ty in ("dynamic_tool", "file_change", "file_search", "web_search", "subagent", "user_input_request"):
            if ty == "dynamic_tool":
                name, inp, output = d.get("toolName") or "tool", d.get("input"), d.get("output")
            elif ty == "file_change":
                name, inp = "file_change", {"file": d.get("fileName"), "title": d.get("title")}
                output = d.get("diffStr") if failed else ""
            elif ty == "file_search":
                name, inp, output = "file_search", {"pattern": d.get("pattern"), "title": d.get("title")}, d.get("results")
            elif ty == "web_search":
                name, inp, output = "web_search", {"query": d.get("patterns")}, d.get("results")
            elif ty == "subagent":
                meta["spawned"] += 1
                name, inp, output = "subagent", {"description": d.get("title"), "prompt": head(d.get("prompt") or "", 300)}, d.get("result")
            else:
                name, inp, output = "ask_user", {"questions": [q.get("question") for q in (d.get("questions") or []) if isinstance(q, dict)]}, d.get("questionAnswer")
            fpath = None
            if isinstance(inp, dict) and name.split(".")[-1].lower() in ("read", "read_file", "view"):
                fpath = inp.get("filePath") or inp.get("file_path") or inp.get("path")
            c = mk_call(st, name, inp, cid=d.get("id"), file=fpath)
            items.append(c)
            otext = output if isinstance(output, str) else ("" if output in (None, {}, []) else json.dumps(output, ensure_ascii=False))
            err = failed or (isinstance(output, dict) and "error" in output)
            items.append(mk_res(en, c, otext, err=err))
        elif ty == "compaction":
            if failed:
                items.append({"k": "error", "ts": en, "text": "context compaction failed"})
            else:
                meta["compactions"] += 1
                items.append({"k": "compact", "ts": en, "text": "context compaction"})
        elif ty == "error":
            fl = d.get("failure") or {}
            items.append({"k": "error", "ts": en, "text": "%s: %s" % (d.get("title") or "error", one_line(fl.get("message") or ""))})
        elif ty == "run_interrupt_request":
            items.append({"k": "interrupt", "ts": st, "text": d.get("message") or "interrupt requested"})
    t3_tokens(conn, thread_id, meta)
    return items, meta


# --------------------------------------------------------------------------
# per-session statistics


def compute(items, meta):
    """Derive every number the digest shows from the normalised items."""
    s = {}
    humans = [(i, it) for i, it in enumerate(items) if it["k"] == "human"]
    s["human_prompts"] = len(humans)
    s["tasks"] = [(i, it) for i, it in enumerate(items) if it["k"] == "task"]
    calls = [(i, it) for i, it in enumerate(items) if it["k"] == "call" and it.get("counted", True)]
    s["tool_calls"] = len(calls)
    s["failed_calls"] = sum(1 for _, c in calls if c.get("err"))
    s["result_chars"] = sum((c.get("res") or {}).get("size", 0) for _, c in calls)
    s["interrupts"] = sum(1 for it in items if it["k"] == "interrupt")
    s["injected"] = sum(1 for it in items if it["k"] == "inj")
    tok = meta["tokens"]
    s["tokens"] = dict(tok)
    s["tokens_total"] = tok["in"] + tok["cr"] + tok["cw"] + tok["out"]
    start, end = meta["start"], meta["end"]
    s["wall_s"] = (end - start) if (start is not None and end is not None) else None
    idle = 0.0
    prev = None
    for it in items:
        ts = it.get("ts")
        if ts is None:
            continue
        if prev is not None and it["k"] == "human" and ts - prev > IDLE_BEFORE_PROMPT:
            idle += ts - prev
        prev = ts if prev is None or ts > prev else prev
    s["active_s"] = (s["wall_s"] - idle) if s["wall_s"] is not None else None

    # tool tally
    tally = {}
    for _, c in calls:
        t = tally.setdefault(c["tool"], [0, 0, 0])
        t[0] += 1
        t[1] += 1 if c.get("err") else 0
        t[2] += (c.get("res") or {}).get("size", 0)
    s["tally"] = tally
    # commands
    # commands: one row per program; a shell call that chains several programs counts for each
    # of them (column 0), and once as its first program (column 5); failures, output chars and
    # seconds belong to the whole shell call
    cmds = {}
    for _, c in calls:
        if not c.get("cmd"):
            continue
        progs = command_programs(c["cmd"])
        for j, n in enumerate(progs):
            e = cmds.setdefault(n, [0, 0, 0, 0.0, 0, 0])
            e[0] += 1
            e[5] += 1 if j == 0 else 0
            e[1] += 1 if c.get("err") else 0
            e[2] += (c.get("res") or {}).get("size", 0)
            if c.get("dur") is not None:
                e[3] += c["dur"]
                e[4] += 1
    s["commands"] = cmds
    s["shell_calls"] = sum(1 for _, c in calls if c.get("cmd"))
    # failures with retry flag
    key_positions = collections.defaultdict(list)
    for i, c in calls:
        key_positions[c["key"]].append(i)
    fails = []
    mutating = [i for i, c in calls if changes_state(c)]
    for i, c in calls:
        if not c.get("err"):
            continue
        later = [j for j in key_positions[c["key"]] if j > i]
        label = command_label(c["cmd"]) if c.get("cmd") else c["tool"]
        nxt = later[0] if later else None
        changed = nxt is not None and any(i < m < nxt for m in mutating)
        fails.append({"pos": i, "tool": c["tool"], "label": label, "inp": c.get("inp") or "",
                      "error": one_line((c.get("res") or {}).get("text") or ""), "retried": bool(later),
                      "rerun_at": nxt, "blind": nxt is not None and not changed, "after_change": changed})
    s["fails"] = fails
    s["blind_retries"] = sum(1 for f in fails if f["blind"])
    s["reruns_after_change"] = sum(1 for f in fails if f["after_change"])
    # repeats
    reps = []
    for key, poss in key_positions.items():
        if len(poss) >= 2:
            c = items[poss[0]]
            if c["tool"] in ("file_change", "apply_patch", "Edit", "Write", "MultiEdit"):
                continue  # repeated edits are normal work, and T3 records no file for them
            reps.append({"tool": c["tool"], "inp": c.get("inp") or "", "count": len(poss), "positions": poss,
                         "chars": sum((items[p].get("res") or {}).get("size", 0) for p in poss)})
    reps.sort(key=lambda r: (-r["count"], -r["chars"], r["positions"][0]))
    s["repeats"] = reps
    reads = {}
    for i, c in calls:
        fl = c.get("files") or ([c["file"]] if c.get("file") else [])
        for fpath in fl:
            e = reads.setdefault(fpath, [0, 0, []])
            e[0] += 1
            e[1] += (c.get("res") or {}).get("size", 0) // max(1, len(fl))
            e[2].append(i)
    s["reads"] = reads
    # biggest results
    big = []
    for i, it in enumerate(items):
        if it["k"] == "res" and it.get("counted", True):
            big.append((it.get("size", 0), i, it))
    big.sort(key=lambda x: (-x[0], x[1]))
    s["biggest"] = big[:10]
    last_asst = [it for it in items if it["k"] == "asst"]
    s["final_text"] = last_asst[-1]["text"] if last_asst else ""
    s["compactions"] = meta["compactions"]
    return s


# --------------------------------------------------------------------------
# discovery


def git(args, cwd):
    try:
        r = subprocess.run(["git"] + args, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                           universal_newlines=True, timeout=20)
        return r.stdout if r.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


_REMOTE_CACHE = {}


def remotes_of(path):
    if path in _REMOTE_CACHE:
        return _REMOTE_CACHE[path]
    res = set()
    if os.path.isdir(path):
        o = git(["remote", "-v"], path)
        if o:
            for line in o.splitlines():
                parts = line.split()
                if len(parts) >= 2:
                    res.add(norm_remote(parts[1]))
    _REMOTE_CACHE[path] = res
    return res


def repo_identity(repo):
    repo = os.path.abspath(repo)
    top = git(["rev-parse", "--show-toplevel"], repo)
    ident = {"toplevel": None, "paths": [], "remotes": [], "name": None, "is_git": bool(top)}
    paths = set()
    if top:
        top = norm_path(top.strip())
        ident["toplevel"] = top
        paths.add(top)
        common = git(["rev-parse", "--path-format=absolute", "--git-common-dir"], top)
        if common:
            c = norm_path(common.strip())
            if os.path.basename(c) == ".git":
                paths.add(os.path.dirname(c))
        wt = git(["worktree", "list", "--porcelain"], top) or ""
        for line in wt.splitlines():
            if line.startswith("worktree "):
                paths.add(norm_path(line[9:].strip()))
        ident["remotes"] = sorted(remotes_of(top))
        main = sorted(p for p in paths if os.path.isdir(os.path.join(p, ".git")))
        ident["name"] = os.path.basename(main[0] if main else top)
    else:
        p = norm_path(repo)
        ident["toplevel"] = p
        paths.add(p)
        ident["name"] = os.path.basename(p)
    ident["paths"] = sorted(paths)
    return ident


class Matcher:
    """Decides whether a cwd / remote belongs to the repo, and says how."""

    def __init__(self, ident):
        self.ident = ident
        self.remotes = set(ident["remotes"])
        self.paths = set(ident["paths"])      # from git
        self.t3_paths = set()                  # worktree / workspace paths known to T3
        self.extra_paths = set()               # cwds of sessions matched by remote
        self.cache = {}

    def roots(self):
        return sorted(self.paths | self.t3_paths | self.extra_paths, key=lambda p: (-len(p), p))

    def match(self, cwd, remote=None):
        if remote and self.remotes and norm_remote(remote) in self.remotes:
            return "git remote"
        p = norm_path(cwd) if cwd else ""
        if not p:
            return None
        key = p
        if key in self.cache:
            return self.cache[key]
        res = None
        if under(p, sorted(self.paths, key=len, reverse=True)):
            res = "git path"
        elif under(p, sorted(self.t3_paths, key=len, reverse=True)):
            res = "T3 worktree path"
        elif under(p, sorted(self.extra_paths, key=len, reverse=True)):
            res = "path of a remote-matched session"
        elif os.path.isdir(p):
            top = git(["rev-parse", "--show-toplevel"], p)
            if top and self.remotes and (remotes_of(norm_path(top.strip())) & self.remotes):
                res = "git remote of cwd"
        else:
            name = self.ident.get("name") or ""
            if len(name) >= 4 and name.lower() not in GENERIC_NAMES and self.ident.get("is_git"):
                segs = p.split("/")
                if name in segs:
                    # the deepest existing ancestor must not be a git repo with a different remote
                    anc = p
                    while anc and not os.path.isdir(anc):
                        anc = os.path.dirname(anc)
                    top = git(["rev-parse", "--show-toplevel"], anc) if anc and anc != "/" else None
                    if not top or (remotes_of(norm_path(top.strip())) & self.remotes):
                        res = "path pattern"
        self.cache[key] = res
        return res


# --------------------------------------------------------------------------
# scan


# ---------------------------------------------------------------- OpenCode

def oc_connect():
    return sqlite3.connect("file:%s?mode=ro" % OPENCODE_DB, uri=True, timeout=10)


def parse_opencode(conn, sid, agent_texts=None):
    """OpenCode >= 2 keeps a session as rows of session_message(type, seq, data)."""
    items, meta = [], new_meta()
    agent_texts = agent_texts or set()
    rows = conn.execute("SELECT type, time_created, data FROM session_message WHERE session_id = ? ORDER BY seq", (sid,)).fetchall()
    for ty, tcreated, data in rows:
        d = _jl(data)
        if not d:
            meta["bad_lines"] += 1
            continue
        tm = d.get("time") or {}
        ts = parse_ts(tm.get("created") or tcreated)
        _touch(meta, ts)
        if ty == "user":
            txt = d.get("text") or ""
            if d.get("files"):
                txt += " [%d attached files]" % len(d["files"])
            kind, clean = classify_text(txt)
            if kind == "human" and agent_key(clean) in agent_texts:
                kind = "task"
            items.append({"k": kind, "ts": ts, "text": ptext(kind, clean)})
        elif ty == "synthetic":
            items.append({"k": "inj", "ts": ts, "text": keep(d.get("text") or ""), "why": "synthetic"})
        elif ty == "compaction":
            meta["compactions"] += 1
            items.append({"k": "compact", "ts": ts, "text": "compaction (%s)" % d.get("reason", "?")})
            _oc_usage(meta, d)
        elif ty == "idle" and d.get("error"):
            items.append({"k": "error", "ts": ts, "text": one_line(text_of(d.get("error")))[:400]})
        elif ty == "assistant":
            _oc_usage(meta, d)
            model = (d.get("model") or {}).get("id")
            if model:
                meta["models"][model] += 1
            if d.get("error"):
                items.append({"k": "error", "ts": ts, "text": one_line(text_of(d.get("error")))[:400]})
            for b in d.get("content") or []:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "text" and (b.get("text") or "").strip():
                    items.append({"k": "asst", "ts": parse_ts((b.get("time") or {}).get("created")) or ts, "text": keep(b["text"])})
                elif b.get("type") == "tool":
                    st = b.get("state") or {}
                    name = b.get("name") or "?"
                    inp = st.get("input")
                    bt = b.get("time") or {}
                    t0 = parse_ts(bt.get("ran") or bt.get("created")) or ts
                    t1 = parse_ts(bt.get("completed")) or t0
                    cmd = inp.get("command") if isinstance(inp, dict) and name in ("shell", "bash") else None
                    fpath = (inp.get("filePath") or inp.get("path")) if isinstance(inp, dict) and name == "read" else None
                    fl = files_read_by_command(cmd) if cmd else ([fpath] if fpath else [])
                    c = mk_call(t0, name, inp, cid=b.get("id"), cmd=cmd, file=fl[0] if fl else None)
                    c["files"] = fl
                    if name in ("task", "agent", "subagent"):
                        meta["spawned"] += 1
                    items.append(c)
                    md = st.get("metadata") or {}
                    ex = md.get("exit")
                    err = st.get("status") == "error" or (ex not in (None, 0))
                    rtext = text_of(st.get("content")) if st.get("content") is not None else text_of(st.get("error"))
                    r = mk_res(t1, c, rtext, err=err)
                    if ex not in (None, 0):
                        r["text"] = ("exit %s: " % ex) + r["text"]
                    items.append(r)
    return items, meta


def _oc_usage(meta, d):
    tk = d.get("tokens") or {}
    if not tk:
        return
    cache = tk.get("cache") or {}
    i, cr, cw = int(tk.get("input") or 0), int(cache.get("read") or 0), int(cache.get("write") or 0)
    tok = meta["tokens"]
    tok["in"] += i
    tok["cr"] += cr
    tok["cw"] += cw
    tok["out"] += int(tk.get("output") or 0) + int(tk.get("reasoning") or 0)
    meta["usage_records"] += 1
    if i + cr + cw and (meta["peak_ctx"] is None or i + cr + cw > meta["peak_ctx"]):
        meta["peak_ctx"] = i + cr + cw
    if isinstance(d.get("cost"), (int, float)):
        meta["cost"] = (meta["cost"] or 0.0) + float(d["cost"])


# ---------------------------------------------------------------- Pi

def pi_head(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for i, line in enumerate(f):
                if i > 5:
                    break
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                if isinstance(d, dict) and d.get("type") == "session":
                    return {"id": d.get("id"), "cwd": d.get("cwd"), "start": parse_ts(d.get("timestamp"))}
    except OSError:
        return None
    return None


def parse_pi(path, agent_texts=None):
    """Pi (pi.dev) session JSONL: session / model_change / message(user|assistant|toolResult|system) / compaction."""
    items, meta = [], new_meta()
    agent_texts = agent_texts or set()
    calls = {}
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                d = json.loads(line)
            except ValueError:
                meta["bad_lines"] += 1
                continue
            if not isinstance(d, dict):
                meta["bad_lines"] += 1
                continue
            t = d.get("type")
            ts = parse_ts(d.get("timestamp"))
            if t == "session":
                meta["session_id"] = d.get("id")
                meta["cwd"] = d.get("cwd")
                _touch(meta, ts)
            elif t == "session_info" and d.get("name"):
                meta["title"] = d.get("name")
            elif t == "compaction":
                meta["compactions"] += 1
                items.append({"k": "compact", "ts": ts, "text": "compaction (%s tokens before)" % d.get("tokensBefore", "?")})
            elif t == "message":
                m = d.get("message") or {}
                role = m.get("role")
                if role in ("user", "assistant", "toolResult"):
                    _touch(meta, ts)
                content = m.get("content")
                if role == "user":
                    txt = text_of(content) if not isinstance(content, str) else content
                    kind, clean = classify_text(txt)
                    if kind == "human" and agent_key(clean) in agent_texts:
                        kind = "task"
                    items.append({"k": kind, "ts": ts, "text": ptext(kind, clean)})
                elif role == "assistant":
                    if m.get("model"):
                        meta["models"][m["model"]] += 1
                    u = m.get("usage") or {}
                    if u:
                        i, cr, cw = int(u.get("input") or 0), int(u.get("cacheRead") or 0), int(u.get("cacheWrite") or 0)
                        tok = meta["tokens"]
                        tok["in"] += i
                        tok["cr"] += cr
                        tok["cw"] += cw
                        tok["out"] += int(u.get("output") or 0)
                        meta["usage_records"] += 1
                        if i + cr + cw and (meta["peak_ctx"] is None or i + cr + cw > meta["peak_ctx"]):
                            meta["peak_ctx"] = i + cr + cw
                        cost = (u.get("cost") or {}).get("total") if isinstance(u.get("cost"), dict) else None
                        if isinstance(cost, (int, float)):
                            meta["cost"] = (meta["cost"] or 0.0) + float(cost)
                    if m.get("errorMessage"):
                        items.append({"k": "error", "ts": ts, "text": one_line(m["errorMessage"])[:400]})
                    for b in content or []:
                        if not isinstance(b, dict):
                            continue
                        if b.get("type") == "text" and (b.get("text") or "").strip():
                            items.append({"k": "asst", "ts": ts, "text": keep(b["text"])})
                        elif b.get("type") == "toolCall":
                            name = b.get("name") or "?"
                            inp = b.get("arguments")
                            cmd = inp.get("command") if isinstance(inp, dict) and name in ("bash", "shell") else None
                            fpath = (inp.get("path") or inp.get("file_path")) if isinstance(inp, dict) and name == "read" else None
                            fl = files_read_by_command(cmd) if cmd else ([fpath] if fpath else [])
                            c = mk_call(ts, name, inp, cid=b.get("id"), cmd=cmd, file=fl[0] if fl else None)
                            c["files"] = fl
                            if name in ("task", "agent", "subagent", "spawn_agent"):
                                meta["spawned"] += 1
                            calls[b.get("id")] = c
                            items.append(c)
                elif role == "toolResult":
                    c = calls.get(m.get("toolCallId"))
                    r = mk_res(ts, c, text_of(content), err=m.get("isError") is True)
                    if c is not None and isinstance(m.get("durationMs"), (int, float)):
                        c["dur"] = m["durationMs"] / 1000.0
                    items.append(r)
    return items, meta


# ---------------------------------------------------------------- generic import format

IMPORT_SPEC = """\
session_digest.py import format (version 1)

One JSON object per line (JSONL). Lines for several sessions may share a file and
may interleave; within a session, order the lines in the order things happened.
Unknown keys are ignored. Every line has:

  session  string   session id, unique within the harness
  kind     string   one of the kinds below
  ts       string|number   ISO-8601 time ("2026-11-18T10:37:53Z") or epoch seconds/ms
                    (optional, but durations and windows need it)

kind "meta"        once per session, anywhere (later values win)
  tool     harness name, e.g. "aider"          title   session title
  cwd      working directory (used to match the repo; omit to always include)
  repo     git remote URL (also used to match)  branch  git branch
  model    model name                           parent  parent session id (subagents)
kind "prompt"      text typed by the developer
  text     the prompt
  author   "human" (default), "agent" (a brief written by another agent) or "injected"
kind "assistant"   assistant text shown to the developer
  text
kind "call"        a tool call
  id       call id (links the result)           tool    tool name, e.g. "shell", "read"
  input    object or string                     cmd     the shell command, for shell calls
kind "result"      the tool result
  id       call id                               text    result text (or give size)
  size     result size in chars, if text is omitted
  error    true when the call failed            duration_s  seconds the call took
kind "usage"       token usage of one model request (summed per session)
  input    uncached input tokens   cache_read   cache_write   output   model   cost (USD)
kind "compaction"  the context was compacted
  text     optional note

Sessions are matched to the repo by meta.cwd / meta.repo when given and filtered by
--since/--until on their first timestamp. Pass files or directories (*.jsonl) with
`scan --import PATH`, repeatable.
"""

IMPORT_EXAMPLE = """\
{"session":"s1","kind":"meta","tool":"aider","cwd":"/work/myrepo","model":"gpt-x","title":"fix login"}
{"session":"s1","ts":"2026-11-18T10:00:00Z","kind":"prompt","text":"fix the login bug"}
{"session":"s1","ts":"2026-11-18T10:00:05Z","kind":"call","id":"c1","tool":"shell","cmd":"pnpm test"}
{"session":"s1","ts":"2026-11-18T10:00:40Z","kind":"result","id":"c1","text":"2 failed","error":true}
{"session":"s1","ts":"2026-11-18T10:00:41Z","kind":"usage","input":1200,"cache_read":8000,"output":300}
{"session":"s1","ts":"2026-11-18T10:01:00Z","kind":"assistant","text":"Fixed; tests pass now."}
"""


def iter_import_files(paths):
    out_ = []
    for p in paths:
        if os.path.isdir(p):
            out_.extend(sorted(glob.glob(os.path.join(p, "**", "*.jsonl"), recursive=True)))
        else:
            out_.append(p)
    return out_


def import_index(path):
    """session id -> {meta, start, lines}; one pass over the file."""
    res = collections.OrderedDict()
    bad = 0
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                d = json.loads(line)
            except ValueError:
                bad += 1
                continue
            if not isinstance(d, dict) or not d.get("session"):
                bad += 1
                continue
            e = res.setdefault(str(d["session"]), {"meta": {}, "start": None, "lines": 0})
            e["lines"] += 1
            if d.get("kind") == "meta":
                e["meta"].update({k: v for k, v in d.items() if k not in ("session", "kind")})
            t = parse_ts(d.get("ts"))
            if t is not None and (e["start"] is None or t < e["start"]):
                e["start"] = t
    return res, bad


def parse_import(path, sid, agent_texts=None):
    items, meta = [], new_meta()
    calls = {}
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                d = json.loads(line)
            except ValueError:
                meta["bad_lines"] += 1
                continue
            if not isinstance(d, dict) or str(d.get("session")) != sid:
                continue
            k = d.get("kind")
            ts = parse_ts(d.get("ts"))
            if k != "meta":
                _touch(meta, ts)
            if k == "meta":
                meta["cwd"] = d.get("cwd") or meta["cwd"]
                meta["branch"] = d.get("branch") or meta["branch"]
                meta["title"] = d.get("title") or meta["title"]
                if d.get("model"):
                    meta["models"][d["model"]] += 1
            elif k == "prompt":
                author = d.get("author") or "human"
                txt = d.get("text") or ""
                kind = {"human": "human", "agent": "task", "injected": "inj"}.get(author, "human")
                items.append({"k": kind, "ts": ts, "text": ptext(kind, txt)})
            elif k == "assistant":
                if (d.get("text") or "").strip():
                    items.append({"k": "asst", "ts": ts, "text": keep(d["text"])})
            elif k == "call":
                tool = d.get("tool") or "?"
                inp = d.get("input")
                cmd = d.get("cmd") or (inp.get("command") if isinstance(inp, dict) and tool in ("shell", "bash", "Bash") else None)
                fpath = (inp.get("path") or inp.get("file_path") or inp.get("filePath")) if isinstance(inp, dict) and tool.lower() in ("read", "read_file", "view") else None
                fl = files_read_by_command(cmd) if cmd else ([fpath] if fpath else [])
                c = mk_call(ts, tool, inp if inp is not None else (cmd or {}), cid=d.get("id"), cmd=cmd, file=fl[0] if fl else None)
                c["files"] = fl
                if tool.lower() in ("task", "agent", "subagent", "spawn_agent"):
                    meta["spawned"] += 1
                calls[d.get("id")] = c
                items.append(c)
            elif k == "result":
                c = calls.get(d.get("id"))
                txt = d.get("text")
                r = mk_res(ts, c, txt if isinstance(txt, str) else ("" if txt is None else json.dumps(txt)),
                           err=d.get("error") is True, size=None if txt is not None else int(d.get("size") or 0))
                if c is not None and isinstance(d.get("duration_s"), (int, float)):
                    c["dur"] = float(d["duration_s"])
                items.append(r)
            elif k == "usage":
                tok = meta["tokens"]
                i, cr, cw = int(d.get("input") or 0), int(d.get("cache_read") or 0), int(d.get("cache_write") or 0)
                tok["in"] += i
                tok["cr"] += cr
                tok["cw"] += cw
                tok["out"] += int(d.get("output") or 0)
                meta["usage_records"] += 1
                if i + cr + cw and (meta["peak_ctx"] is None or i + cr + cw > meta["peak_ctx"]):
                    meta["peak_ctx"] = i + cr + cw
                if d.get("model"):
                    meta["models"][d["model"]] += 1
                if isinstance(d.get("cost"), (int, float)):
                    meta["cost"] = (meta["cost"] or 0.0) + float(d["cost"])
            elif k == "compaction":
                meta["compactions"] += 1
                items.append({"k": "compact", "ts": ts, "text": d.get("text") or "compaction"})
    return items, meta


# --------------------------------------------------------------------------
# adapters: one class per harness store


class Adapter:
    """A harness store. `discover` adds the repo's sessions to the scan; `parse_native`
    (a module-level registry, so `show` works without a scan) turns one native ref into items.

    A session dict carries `natives`: a list of (kind, native_id, key) where key is a file
    path or a database key that `parse_native` understands."""

    name = ""

    def __init__(self, scan):
        self.scan = scan
        self._index = None

    def location(self):
        return ""

    def available(self):
        return False

    def resolve(self, native_id):
        """native id (as another store, e.g. T3, records it) -> key, or None."""
        return None

    def discover(self):
        pass

    # shared helpers
    def src(self):
        return self.scan.src(self.name, location=self.location())

    def begin(self):
        """Common preamble; returns the Sources entry or None when the store is skipped."""
        s = self.src()
        if self.name not in self.scan.tools:
            s["notes"].append("not requested (--tools)")
            return None
        if not self.available():
            s["notes"].append("not found")
            return None
        s["found"] = True
        return s


class ClaudeAdapter(Adapter):
    name = "claude"

    def location(self):
        return os.path.join(CLAUDE_HOME, "projects")

    def available(self):
        return os.path.isdir(self.location())

    def index(self):
        if self._index is None:
            main, sub = {}, {}
            if self.available():
                for p in glob.glob(os.path.join(self.location(), "*", "*.jsonl")):
                    main[os.path.basename(p)[:-6]] = p
                for p in glob.glob(os.path.join(self.location(), "*", "*", "subagents", "agent-*.jsonl")):
                    sub[os.path.basename(p)[6:-6]] = p
            self._index = (main, sub)
        return self._index

    def resolve(self, native_id, sub=False):
        return self.index()[1 if sub else 0].get(native_id)

    def discover(self):
        s = self.begin()
        if s is None:
            return
        scan = self.scan
        main_idx, sub_idx = self.index()
        main_by_native = {}
        for sid_native in sorted(main_idx):
            path = main_idx[sid_native]
            key = "claude:" + sid_native
            if key in scan.claimed:
                if scan.claimed[key] is not None:
                    main_by_native[sid_native] = scan.claimed[key]
                continue
            try:
                if os.path.getmtime(path) < scan.t_from:
                    continue
            except OSError:
                continue
            h = claude_head(path)
            if h is None:
                s["skipped"]["unreadable transcript"] += 1
                continue
            if not scan.in_window(h["start"]):
                continue
            how = scan.m.match(h["cwd"])
            if not how:
                continue
            helper = (h.get("entrypoint") == "sdk-cli") or bool(_HELPER.match((h.get("first_prompt") or "").lstrip()))
            sess = {"id": sid_native, "tool": "claude", "store": "claude", "provider": "claudeAgent", "title": None,
                    "start_hint": h["start"], "cwd": h["cwd"], "branch": h.get("branch"), "match": how,
                    "natives": [("claude", sid_native, path)], "sources": [{"kind": "claude", "key": sid_native, "path": path}],
                    "is_subagent": False}
            scan.claim(key, sid_native)
            if helper:
                sess["utility"] = True
                scan.utility.append(sess)
                s["skipped"]["T3 text-generation helper (commit/branch/PR/title)"] += 1
                continue
            s["how"][how] += 1
            scan.sessions.append(sess)
            main_by_native[sid_native] = sid_native
        for aid in sorted(sub_idx):
            path = sub_idx[aid]
            key = "claude-sub:" + aid
            if key in scan.claimed:
                continue
            parent = main_by_native.get(os.path.basename(os.path.dirname(os.path.dirname(path))))
            if parent is None:
                continue
            h = claude_head(path, max_lines=50) or {}
            if not scan.in_window(h.get("start")):
                continue
            metaj = {}
            try:
                with open(path[:-6] + ".meta.json", "r", encoding="utf-8") as f:
                    metaj = json.load(f)
            except (OSError, ValueError):
                pass
            sid = "agent-" + aid
            sess = {"id": sid, "tool": "claude", "store": "claude", "provider": "claudeAgent",
                    "title": "%s: %s" % (metaj.get("agentType", "subagent"), metaj.get("description", "")),
                    "start_hint": h.get("start"), "cwd": h.get("cwd"), "branch": h.get("branch"), "match": "subagent of matched session",
                    "natives": [("claude-sub", aid, path)], "sources": [{"kind": "claude-sub", "key": aid, "path": path}],
                    "is_subagent": True, "parent": parent}
            scan.claim(key, sid)
            s["how"]["subagent of matched session"] += 1
            scan.sessions.append(sess)


class CodexAdapter(Adapter):
    name = "codex"

    def location(self):
        return CODEX_HOME

    def available(self):
        return os.path.isdir(CODEX_HOME)

    def index(self):
        if self._index is None:
            idx = {}
            for sub in ("sessions", "archived_sessions"):
                for p in sorted(glob.glob(os.path.join(CODEX_HOME, sub, "**", "rollout-*.jsonl"), recursive=True)):
                    m = re.search(r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\.jsonl$", p)
                    if m and m.group(1) not in idx:
                        idx[m.group(1)] = p
            self._index = idx
        return self._index

    def resolve(self, native_id):
        return self.index().get(native_id)

    def discover(self):
        s = self.begin()
        if s is None:
            return
        scan = self.scan
        rows = {}
        dbs = sorted(glob.glob(os.path.join(CODEX_HOME, "state_*.sqlite")),
                     key=lambda p: int(re.search(r"state_(\d+)", p).group(1)) if re.search(r"state_(\d+)", p) else 0)
        if dbs:
            db = dbs[-1]
            try:
                conn = sqlite3.connect("file:%s?mode=ro" % db, uri=True, timeout=10)
                cols = {r[1] for r in conn.execute("PRAGMA table_info(threads)")}
                want = [c for c in ("id", "rollout_path", "created_at", "cwd", "title", "git_origin_url", "git_branch", "model", "archived", "source") if c in cols]
                if "id" in want and "rollout_path" in want:
                    q = "SELECT %s FROM threads" % ", ".join(want)
                    if "created_at" in cols:
                        q += " WHERE created_at >= %d" % int(scan.t_from - 86400)
                    for r in conn.execute(q):
                        d = dict(zip(want, r))
                        rows[d["id"]] = d
                    s["notes"].append("index %s read (%d threads created since the window start, any repo)" % (os.path.basename(db), len(rows)))
                else:
                    s["notes"].append("index %s has no usable threads table; scanned rollout files" % os.path.basename(db))
                conn.close()
            except sqlite3.Error as e:
                s["notes"].append("index unreadable (%s); scanned rollout files" % e)
        else:
            s["notes"].append("no state_*.sqlite index; scanned rollout files")
        idx = self.index()
        for uid in sorted(idx):
            path = idx[uid]
            if ("codex:" + uid) in scan.claimed:
                continue
            try:
                if os.path.getmtime(path) < scan.t_from:
                    continue
            except OSError:
                continue
            h = codex_head(path)
            if h is None:
                s["skipped"]["unreadable rollout"] += 1
                continue
            row = rows.get(uid, {})
            start = h.get("start") or parse_ts(row.get("created_at"))
            if not scan.in_window(start):
                continue
            remote = row.get("git_origin_url") or h.get("remote")
            cwd = h.get("cwd") or row.get("cwd")
            how = scan.m.match(cwd, remote)
            if not how:
                continue
            if how == "git remote" and cwd:
                scan.m.extra_paths.add(norm_path(cwd))
            sess = {"id": uid, "tool": "codex", "store": "codex", "provider": "codex", "title": row.get("title"),
                    "start_hint": start, "cwd": cwd, "branch": h.get("branch") or row.get("git_branch"),
                    "model_hint": row.get("model"), "match": how, "natives": [("codex", uid, path)],
                    "sources": [{"kind": "codex", "key": uid, "path": path}], "native_parent": h.get("parent"),
                    "is_subagent": bool(h.get("parent"))}
            scan.claim("codex:" + uid, uid)
            s["how"][how] += 1
            scan.sessions.append(sess)
        scan.m.cache.clear()


class OpenCodeAdapter(Adapter):
    name = "opencode"

    def location(self):
        return OPENCODE_DB

    def available(self):
        return os.path.exists(OPENCODE_DB)

    def conn(self):
        if self._index is None:
            self._index = {"conn": None, "ids": set()}
            if self.available():
                try:
                    c = oc_connect()
                    have = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                    if {"session_v2", "session_message"} <= have:
                        self._index["conn"] = c
                        self._index["ids"] = {r[0] for r in c.execute("SELECT id FROM session_v2")}
                        self._index["legacy"] = c.execute("SELECT count(*) FROM session").fetchone()[0] if "session" in have else 0
                except sqlite3.Error as e:
                    self._index["error"] = str(e)
        return self._index

    def resolve(self, native_id):
        return native_id if native_id in self.conn()["ids"] else None

    def discover(self):
        s = self.begin()
        if s is None:
            return
        scan = self.scan
        st = self.conn()
        conn = st["conn"]
        if conn is None:
            s["notes"].append("schema not recognised (no session_v2/session_message tables)%s" % ((": " + st["error"]) if st.get("error") else ""))
            if os.path.isdir(os.path.join(os.path.dirname(OPENCODE_DB), "storage")):
                s["notes"].append("legacy JSON storage/ layout present but not supported")
            return
        if st.get("legacy"):
            s["notes"].append("%d sessions in the legacy `session` table were not read" % st["legacy"])
        # session_v2 is small (one row per session); no time index exists, so it is read whole
        rows = conn.execute("SELECT id, parent_id, directory, title, time_created, model FROM session_v2 WHERE time_updated >= ?",
                            (int(scan.t_from * 1000),)).fetchall()
        for sid, parent, directory, title, created, model in sorted(rows):
            key = "opencode:" + sid
            if key in scan.claimed:
                continue
            start = parse_ts(created)
            if not scan.in_window(start):
                continue
            how = scan.m.match(directory)
            if not how:
                continue
            sess = {"id": sid, "tool": "opencode", "store": "opencode", "provider": "opencode", "title": title,
                    "start_hint": start, "cwd": directory, "match": how, "model_hint": (_jl(model).get("id") if model else None),
                    "natives": [("opencode", sid, sid)], "sources": [{"kind": "opencode", "key": sid, "path": OPENCODE_DB}],
                    "native_parent": parent, "is_subagent": bool(parent)}
            scan.claim(key, sid)
            s["how"][how] += 1
            scan.sessions.append(sess)


class PiAdapter(Adapter):
    name = "pi"

    def location(self):
        return PI_SESSIONS

    def available(self):
        return os.path.isdir(PI_SESSIONS)

    def index(self):
        if self._index is None:
            self._index = sorted(glob.glob(os.path.join(PI_SESSIONS, "*", "*.jsonl"))) if self.available() else []
        return self._index

    def resolve(self, native_id):
        # T3 records the session file path as Pi's native id
        p = norm_path(native_id) if native_id else ""
        return p if p and p.startswith(norm_path(PI_SESSIONS) + "/") and os.path.isfile(p) else None

    def discover(self):
        s = self.begin()
        if s is None:
            return
        scan = self.scan
        for path in self.index():
            key = "pi:" + norm_path(path)
            if key in scan.claimed:
                continue
            try:
                if os.path.getmtime(path) < scan.t_from:
                    continue
            except OSError:
                continue
            h = pi_head(path)
            if h is None:
                s["skipped"]["unreadable session file"] += 1
                continue
            if not scan.in_window(h["start"]):
                continue
            how = scan.m.match(h["cwd"])
            if not how:
                continue
            sid = h["id"] or os.path.basename(path)[:-6]
            if sid in scan.claimed.values():
                sid = "pi-" + sha(path)[:12]
            sess = {"id": sid, "tool": "pi", "store": "pi", "provider": "pi", "title": None, "start_hint": h["start"],
                    "cwd": h["cwd"], "match": how, "natives": [("pi", norm_path(path), norm_path(path))],
                    "sources": [{"kind": "pi", "key": sid, "path": path}], "is_subagent": False}
            scan.claim(key, sid)
            s["how"][how] += 1
            scan.sessions.append(sess)


class ImportAdapter(Adapter):
    """Sessions written by a converter in the IMPORT_SPEC format (`scan --import`)."""
    name = "import"

    def location(self):
        return ", ".join(self.scan.args.imports or []) or "(none given)"

    def available(self):
        return bool(self.scan.args.imports)

    def discover(self):
        s = self.src()
        if not self.scan.args.imports:
            s["notes"].append("no --import given")
            return
        scan = self.scan
        s["found"] = True
        files = iter_import_files(scan.args.imports)
        s["files"] = []
        for path in files:
            try:
                idx, bad = import_index(path)
            except OSError as e:
                s["notes"].append("cannot read %s: %s" % (path, e))
                continue
            n = 0
            for sid, e in idx.items():
                meta = e["meta"]
                if e["start"] is not None and not scan.in_window(e["start"]):
                    s["skipped"]["outside window"] += 1
                    continue
                how = "imported"
                if meta.get("cwd") or meta.get("repo"):
                    how = scan.m.match(meta.get("cwd"), meta.get("repo"))
                    if not how:
                        s["skipped"]["imported session of another repo"] += 1
                        continue
                    how = "imported, " + how
                key = "import:%s#%s" % (norm_path(path), sid)
                if key in scan.claimed:
                    continue
                tool = str(meta.get("tool") or "import")
                full = sid if sid not in scan.claimed.values() else "imp-" + sha(key)[:12]
                if not re.match(r"^[A-Za-z0-9._-]{1,80}$", full):
                    full = "imp-" + sha(key)[:12]
                sess = {"id": full, "tool": tool, "store": "import", "provider": tool, "title": meta.get("title"),
                        "start_hint": e["start"], "cwd": meta.get("cwd"), "branch": meta.get("branch"), "match": how,
                        "model_hint": meta.get("model"), "natives": [("import", sid, norm_path(path))],
                        "sources": [{"kind": "import", "key": sid, "path": path}],
                        "native_parent": meta.get("parent"), "is_subagent": bool(meta.get("parent"))}
                scan.claim(key, full)
                s["how"][how] += 1
                scan.sessions.append(sess)
                n += 1
            s["files"].append("%s (%d sessions%s)" % (path, n, (", %d malformed lines" % bad) if bad else ""))


T3_PROVIDER_KIND = {"claudeAgent": "claude", "codex": "codex", "opencode": "opencode", "pi": "pi"}


class T3Adapter(Adapter):
    """T3 Code wraps sessions of other harnesses: a thread is one session; its content comes from
    the wrapped native transcript when one resolves, otherwise from T3's own tables."""
    name = "t3"

    def location(self):
        return os.path.join(T3_HOME, "userdata", "statev2.sqlite")

    def available(self):
        return os.path.exists(self.location())

    def native(self, prov, nid):
        """(kind, key) for a provider-thread native ref, or (kind, None) when it does not resolve."""
        ads = self.scan.adapters
        kind = T3_PROVIDER_KIND.get(prov, prov)
        if not nid:
            return kind, None
        if prov == "claudeAgent-subagent":
            a = ads.get("claude")
            return "claude-sub", (a.resolve(nid, sub=True) if a and "claude" in self.scan.tools else None)
        a = ads.get(kind)
        if a is None or kind not in self.scan.tools:
            return kind, None
        return kind, a.resolve(nid)

    def discover(self):
        s = self.begin()
        if s is None:
            return
        scan = self.scan
        db = self.location()
        try:
            conn = t3_connect(db)
            prob = t3_schema_problem(conn)
        except sqlite3.Error as e:
            s["notes"].append("cannot open database: %s" % e)
            return
        if prob:
            s["notes"].append("schema not recognised, missing: %s" % ", ".join(prob))
            return
        scan.t3 = conn
        nproj = conn.execute("SELECT count(*) FROM projection_projects").fetchone()[0]
        if nproj > 20000:
            s["notes"].append("projects table unexpectedly large; matched by exact workspace path only")
            projects = []
            for p in scan.ident["paths"]:
                projects += conn.execute("SELECT project_id, title, workspace_root, deleted_at FROM projection_projects WHERE workspace_root = ?", (p,)).fetchall()
        else:
            projects = conn.execute("SELECT project_id, title, workspace_root, deleted_at FROM projection_projects ORDER BY project_id").fetchall()
        matched = {}
        for pid, title, root, deleted in projects:
            how = scan.m.match(root)
            if how:
                matched[pid] = (title, root, how, deleted)
        s["projects"] = ["%s (%s, %s%s)" % (v[0], v[1], v[2], ", deleted" if v[3] else "") for k, v in sorted(matched.items(), key=lambda kv: kv[1][1])]
        threads = {}
        cols = "thread_id, project_id, title, default_provider, created_at, updated_at, archived_at, deleted_at, payload_json"
        since_iso = datetime.datetime.fromtimestamp(scan.t_from, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        for pid in sorted(matched):
            for r in conn.execute("SELECT %s FROM orchestration_v2_projection_threads WHERE project_id = ? AND updated_at >= ?" % cols, (pid, since_iso)):
                threads[r[0]] = (r, matched[pid][2] if matched[pid][2] != "git path" else "T3 project")
        for p in scan.ident["paths"]:
            for r in conn.execute("SELECT %s FROM orchestration_v2_projection_threads WHERE %s = ?" % (cols, T3_WORKTREE_EXPR), (p,)):
                if r[0] not in threads and (r[5] or "") >= since_iso:
                    threads[r[0]] = (r, "T3 worktree path")
        for pid in sorted(matched):
            for (wp,) in conn.execute("SELECT DISTINCT %s FROM orchestration_v2_projection_threads WHERE project_id = ?" % T3_WORKTREE_EXPR, (pid,)):
                if wp:
                    scan.m.t3_paths.add(norm_path(wp))
            scan.m.t3_paths.add(norm_path(matched[pid][1]))
        scan.m.cache.clear()
        for tid in sorted(threads):
            row, how = threads[tid]
            thread_id, project_id, title, provider, created, updated, archived, deleted, pj = row
            pay = _jl(pj)
            created_t = parse_ts(created)
            pts = conn.execute(
                "SELECT provider_thread_id, provider, payload_json FROM orchestration_v2_projection_provider_threads WHERE thread_id = ? ORDER BY provider_thread_id",
                (thread_id,)).fetchall()
            refs = []
            for ptid, prov, ppj in pts:
                pp = _jl(ppj)
                refs.append((prov, (pp.get("nativeThreadRef") or {}).get("nativeId"), pp.get("createdAt") or ""))
            lineage = pay.get("lineage") or {}
            is_sub = lineage.get("relationshipToParent") == "subagent"
            if not pts and provider == "claudeAgent" and is_sub:
                aid = None
                try:
                    r = conn.execute("SELECT payload_json FROM orchestration_v2_projection_subagents WHERE child_thread_id = ?", (thread_id,)).fetchone()
                    if r:
                        aid = ((_jl(r[0]).get("nativeTaskRef") or {}).get("nativeId"))
                except sqlite3.Error:
                    pass
                if not aid:
                    m = re.search(r"(a[0-9a-f]{16})$", thread_id)
                    aid = m.group(1) if m else None
                refs.append(("claudeAgent-subagent", aid, ""))
            resolved, unresolved = [], []
            for prov, nid, created_at in sorted(refs, key=lambda x: (x[2], str(x[1]))):
                kind, key = self.native(prov, nid)
                if key:
                    resolved.append((kind, nid if kind != "pi" else key, key))
                else:
                    unresolved.append((prov, nid))
            if not scan.in_window(created_t):
                s["skipped"]["thread started outside the window"] += 1
                for kind, nid, key in resolved:  # its transcripts must not come back as standalone sessions
                    scan.claimed.setdefault(kind + ":" + nid, None)
                continue
            sess = {"tool": "t3", "store": "t3", "provider": provider, "t3_thread_id": thread_id,
                    "title": title, "start_hint": created_t, "cwd": pay.get("worktreePath"), "branch": pay.get("branch"),
                    "model_hint": (pay.get("modelSelection") or {}).get("model"), "match": how,
                    "t3_parent": lineage.get("parentThreadId"), "is_subagent": is_sub,
                    "agent_created": pay.get("createdBy") == "agent", "natives": [], "sources": [{"kind": "t3", "key": thread_id}]}
            if refs and not unresolved:
                sess["natives"] = resolved
                kinds = sorted(set(k.split("-")[0] for k, _, _ in resolved))
                sess["tool"] = kinds[0] if len(kinds) == 1 else "mixed"
                sess["store"] = "t3+" + "+".join(kinds)
                sess["sources"] = [{"kind": k, "key": nid, "path": p if k != "opencode" else OPENCODE_DB} for k, nid, p in resolved] + [{"kind": "t3", "key": thread_id}]
                one = len(resolved) == 1
                if one and resolved[0][0] == "claude-sub":
                    sess["id"] = "agent-" + resolved[0][1]
                elif one and resolved[0][0] != "pi":
                    sess["id"] = resolved[0][1]
                else:
                    sess["id"] = thread_id if re.match(r"^[0-9a-f\-]{36}$", thread_id) else "t3-" + sha(thread_id)[:12]
            else:
                if refs and resolved:
                    s["skipped"]["(included) thread mixes parseable and unparseable providers, built from T3 tables"] += 1
                sess["tool"] = T3_PROVIDER_KIND.get(provider, provider)
                sess["id"] = thread_id if re.match(r"^[0-9a-f\-]{36}$", thread_id) else "t3-" + sha(thread_id)[:12]
                for k, nid, p in resolved:
                    scan.claim(k + ":" + nid, sess["id"])
                for prov, nid in unresolved:
                    s["skipped"]["(included) native %s transcript not found, built from T3 tables" % T3_PROVIDER_KIND.get(prov.split("-")[0], prov)] += 1
            for k, nid, p in sess["natives"]:
                scan.claim(k + ":" + nid, sess["id"])
            scan.claim("t3:" + thread_id, sess["id"])
            s["how"][how] += 1
            scan.sessions.append(sess)


# order matters: wrappers first (they claim the natives they wrap), then Codex (its remote
# matches add cwd paths that help the path-only stores)
ADAPTERS = [T3Adapter, CodexAdapter, ClaudeAdapter, OpenCodeAdapter, PiAdapter, ImportAdapter]
TOOL_NAMES = [a.name for a in ADAPTERS if a.name != "import"]


class _Ctx:
    oc = None


def parse_native(kind, nid, key, agent_texts, ctx):
    """Registry used by both scan and show: (kind, native id, key) -> (items, meta)."""
    if kind == "codex":
        return parse_codex(key, agent_texts)
    if kind in ("claude", "claude-sub"):
        return parse_claude(key, agent_texts, sidechain=(kind == "claude-sub"))
    if kind == "opencode":
        if ctx.oc is None:
            ctx.oc = oc_connect()
        return parse_opencode(ctx.oc, key, agent_texts)
    if kind == "pi":
        return parse_pi(key, agent_texts)
    if kind == "import":
        return parse_import(key, nid, agent_texts)
    raise ValueError("no parser for %s" % kind)


class Scan:
    def __init__(self, args):
        self.args = args
        self.tools = set(t.strip() for t in args.tools.split(",") if t.strip())
        unknown = self.tools - set(TOOL_NAMES)
        if unknown:
            sys.exit("unknown --tools: %s (known: %s)" % (", ".join(sorted(unknown)), ",".join(TOOL_NAMES)))
        self.tools.add("import")
        now = time.time()
        self.t_from = now - args.since * 86400
        self.t_to = now - args.until * 86400
        self.ident = repo_identity(args.repo)
        self.m = Matcher(self.ident)
        self.sources = collections.OrderedDict()
        self.sessions = []
        self.utility = []
        self.claimed = {}
        self.errors = []
        self.t3 = None
        self.ctx = _Ctx()
        self.adapters = collections.OrderedDict((a.name, a(self)) for a in ADAPTERS)

    def src(self, name, **kw):
        d = self.sources.setdefault(name, {"found": False, "location": "", "matched": 0, "how": collections.Counter(),
                                           "skipped": collections.Counter(), "notes": []})
        d.update(kw)
        return d

    def in_window(self, t):
        return t is not None and self.t_from <= t <= self.t_to

    def claim(self, key, sid):
        prev = self.claimed.get(key)
        if prev is not None and prev != sid:
            raise AssertionError("source %s mapped to two sessions (%s, %s)" % (key, prev, sid))
        self.claimed[key] = sid

    def parse_session(self, sess):
        agent_texts, t3_users = set(), None
        if sess.get("t3_thread_id") and self.t3 is not None:
            t3_users = t3_thread_user_messages(self.t3, sess["t3_thread_id"])
            agent_texts = {agent_key(m.get("text") or "") for m in t3_users if m.get("createdBy") != "user"}
        return parse_sources(sess, self.t3, agent_texts, t3_users, self.ctx)

    def run(self):
        t0 = time.time()
        for a in self.adapters.values():
            a.discover()
        ids = collections.Counter(s["id"] for s in self.sessions)
        dup = [k for k, v in ids.items() if v > 1]
        if dup:
            raise AssertionError("duplicate session ids: %s" % dup[:5])
        by_t3 = {s["t3_thread_id"]: s["id"] for s in self.sessions if s.get("t3_thread_id")}
        by_native = {}
        for s in self.sessions:
            for k, nid, _ in s.get("natives", []):
                by_native[nid] = s["id"]
        for s in self.sessions:
            if s.get("t3_parent"):
                s["parent"] = by_t3.get(s["t3_parent"]) or s.get("parent")
                s["parent_ref"] = s["t3_parent"]
            if s.get("native_parent"):
                s["parent"] = by_native.get(s["native_parent"]) or s.get("parent")
                s["parent_ref"] = s["native_parent"]
            if s.get("parent") or s.get("parent_ref"):
                s["is_subagent"] = True
        children = collections.defaultdict(list)
        for s in self.sessions:
            if s.get("parent"):
                children[s["parent"]].append(s)
        tops = sorted([s for s in self.sessions if not s.get("parent")], key=lambda s: (-(s.get("start_hint") or 0), s["id"]))
        keep_, cut = [], 0
        for s in tops:
            group = [s]
            stack = [s]
            while stack:
                c = stack.pop(0)
                for g in sorted(children.get(c["id"], []), key=lambda x: ((x.get("start_hint") or 0), x["id"])):
                    group.append(g)
                    stack.append(g)
            if self.args.max_sessions and len(keep_) >= self.args.max_sessions:
                cut += len(group)
                continue
            keep_.extend(group)
        self.cut = cut
        parsed = []
        for s in keep_:
            try:
                items, meta = self.parse_session(s)
            except (OSError, sqlite3.Error, UnicodeError, ValueError, KeyError, TypeError, AttributeError) as e:
                self.errors.append("%s: %s: %s" % (s["id"], type(e).__name__, e))
                self.src(store_family(s["store"]))["skipped"]["unreadable session"] += 1
                continue
            s["items"] = items
            s["meta"] = meta
            s["stats"] = compute(items, meta)
            parsed.append(s)
        self.utility_tokens = {"in": 0, "cr": 0, "cw": 0, "out": 0}
        for u in self.utility:
            try:
                _, meta = parse_claude(u["natives"][0][2])
                for k in self.utility_tokens:
                    self.utility_tokens[k] += meta["tokens"][k]
            except (OSError, ValueError):
                pass
        self.parsed = parsed
        for s in parsed:
            self.src(store_family(s["store"]))["matched"] += 1
        self.elapsed = time.time() - t0


def store_family(store):
    return "t3" if store.startswith("t3") else store


def parse_sources(sess, conn, agent_texts, t3_users=None, ctx=None):
    """Same parse for scan and show: positions are indexes into this list."""
    ctx = ctx or _Ctx()
    items, meta = [], None
    natives = sess.get("natives") or []
    if natives:
        for kind, nid, key in natives:
            it, m = parse_native(kind, nid, key, agent_texts, ctx)
            if sess.get("is_subagent"):
                # a subagent's prompts were written by the agent that spawned it
                for x in it:
                    if x["k"] == "human":
                        x["k"] = "task"
            items.extend(it)
            meta = m if meta is None else merge_meta(meta, m)
    else:
        if conn is None:
            raise ValueError("T3 database not available")
        items, meta = parse_t3(conn, sess["t3_thread_id"])
    if t3_users is not None:
        meta["t3_human"] = sum(1 for m in t3_users if m.get("createdBy") == "user")
    return items, meta


def merge_meta(a, b):
    for k in a["tokens"]:
        a["tokens"][k] += b["tokens"][k]
    a["models"].update(b["models"])
    for k in ("compactions", "bad_lines", "usage_records", "usage_incomplete", "spawned"):
        a[k] += b[k]
    if b["peak_ctx"] is not None and (a["peak_ctx"] is None or b["peak_ctx"] > a["peak_ctx"]):
        a["peak_ctx"] = b["peak_ctx"]
    for k in ("start",):
        if b[k] is not None and (a[k] is None or b[k] < a[k]):
            a[k] = b[k]
    if b["end"] is not None and (a["end"] is None or b["end"] > a["end"]):
        a["end"] = b["end"]
    if b["cost"] is not None:
        a["cost"] = (a["cost"] or 0) + b["cost"]
    a["notes"].extend(b["notes"])
    for k in ("cwd", "branch", "title"):
        a[k] = a[k] or b[k]
    return a


# --------------------------------------------------------------------------
# rendering


def model_of(s):
    ms = s["meta"]["models"]
    if ms:
        return ", ".join(m for m, _ in sorted(ms.items(), key=lambda kv: (-kv[1], kv[0])))
    return s.get("model_hint") or "?"


def main_model(s):
    ms = s["meta"]["models"]
    if ms:
        return sorted(ms.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
    return s.get("model_hint") or "?"


def title_of(s):
    return redact(_title(s))


def _title(s):
    return s.get("title") or s["meta"].get("title") or head(one_line(next((it["text"] for it in s["items"] if it["k"] in ("human", "task")), "")), 60) or "(untitled)"


def item_line(i, it, width):
    k = it["k"]
    ts = fmt_ts(it.get("ts"))[11:16] if it.get("ts") else "--:--"
    if k == "call":
        extra = ""
        if it.get("dur") is not None:
            extra = " (%s)" % fmt_dur(it["dur"])
        if not it.get("counted", True):
            extra += " [wrapper, not counted]"
        body = "CALL %s: %s%s" % (it["tool"], one_line(it.get("inp") or ""), extra)
    elif k == "res":
        flag = " ERROR" if it.get("err") else ""
        body = "RESULT %s %s chars%s: %s" % (it.get("tool", "?"), it.get("size", 0), flag, one_line(it.get("text") or ""))
    else:
        label = {"human": "HUMAN", "inj": "INJECTED", "task": "AGENT-PROMPT", "interrupt": "INTERRUPT", "control": "CONTROL",
                 "asst": "ASSISTANT", "compact": "COMPACTION", "error": "ERROR"}.get(k, k.upper())
        body = "%s: %s" % (label, flat(it.get("text") or ""))
    return head("%5d %s %s" % (i, ts, body), width)


def render_session(s, by_id):
    st, meta = s["stats"], s["meta"]
    L = []
    L.append("# Session %s" % s["id"])
    L.append("")
    L.append("- tool: %s (store: %s, provider: %s)" % (s["tool"], s["store"], s.get("provider") or "?"))
    L.append("- title: %s" % md_cell(title_of(s)))
    L.append("- model(s): %s" % model_of(s))
    L.append("- start: %s; wall %s; active %s (gaps over %ds that end at a human prompt count as idle)" % (
        fmt_ts(meta["start"] or s.get("start_hint")), fmt_dur(st["wall_s"]), fmt_dur(st["active_s"]), IDLE_BEFORE_PROMPT))
    L.append("- cwd: %s; branch: %s; matched by: %s" % (s.get("cwd") or meta.get("cwd") or "?", s.get("branch") or meta.get("branch") or "?", s.get("match")))
    if s.get("t3_thread_id"):
        L.append("- T3 thread: %s%s" % (s["t3_thread_id"], " (agent-created)" if s.get("agent_created") else ""))
    if s.get("is_subagent"):
        L.append("- subagent of: %s" % (s.get("parent") or ("%s (not in this digest)" % s.get("parent_ref"))))
    kids = sorted(by_id.get("_children", {}).get(s["id"], []))
    L.append("- subagents: %d in this digest, %d spawn calls%s" % (len(kids), meta["spawned"], (" (" + ", ".join(kids[:8]) + (" …" if len(kids) > 8 else "") + ")") if kids else ""))
    src = "; ".join("%s %s" % (x["kind"], x.get("path") or x["key"]) for x in s["sources"])
    L.append("- source: %s" % src)
    if meta["bad_lines"]:
        L.append("- malformed lines skipped: %d" % meta["bad_lines"])
    for n in meta["notes"]:
        L.append("- note: %s" % n)
    if meta.get("t3_human") is not None and meta["t3_human"] != st["human_prompts"] and s["store"] != "t3":
        L.append("- note: T3 records %d human messages; the transcript has %d (queued messages arrive merged into one turn)" % (meta["t3_human"], st["human_prompts"]))
    L.append("")
    tok = st["tokens"]
    L.append("## Tokens")
    L.append("")
    L.append("uncached input %s, cache read %s, cache write %s, output %s, total %s; peak context %s; compactions %d; cost %s" % (
        fmt_n(tok["in"]), fmt_n(tok["cr"]), fmt_n(tok["cw"]), fmt_n(tok["out"]), fmt_n(st["tokens_total"]),
        fmt_n(meta["peak_ctx"]) if meta["peak_ctx"] else "?", st["compactions"],
        ("$%.2f (%s)" % (meta["cost"], "Claude Code cost-state, includes in-process subagents" if any(k == "claude" for k, _, _ in s.get("natives", [])) else "sum of per-request costs the store recorded")) if meta["cost"] is not None else "not recorded"))
    if meta["usage_incomplete"]:
        L.append("(%d turns had missing or incomplete usage)" % meta["usage_incomplete"])
    L.append("")
    items = s["items"]
    humans = [(i, it) for i, it in enumerate(items) if it["k"] == "human"]
    L.append("## Human prompts (%d)" % len(humans))
    L.append("")
    if not humans and st["tasks"]:
        L.append("No human prompts; agent-written task prompt:")
        i, it = st["tasks"][0]
        L.append("- [%d] %s" % (i, head(flat(it["text"]), 600)))
    shown = humans if len(humans) <= 25 else humans[:15] + [None] + humans[-10:]
    prev_human = {}
    last = -1
    for i, it in humans:
        prev_human[i] = last
        last = i
    for h in shown:
        if h is None:
            L.append("- … %d prompts omitted; use `show --grep HUMAN` …" % (len(humans) - 25))
            continue
        i, it = h
        L.append("- [%d] %s %s" % (i, fmt_ts(it.get("ts"))[11:] if it.get("ts") else "", head(flat(it["text"]), 600)))
        p0 = prev_human[i]
        if p0 >= 0:
            before = [x for x in items[p0 + 1:i] if x["k"] == "asst"]
            if before:
                L.append("  - assistant just before: %s" % tail(flat(before[-1]["text"]), 200))
            else:
                L.append("  - no assistant text since the previous prompt (sent mid-turn or right after it)")
    L.append("")
    if st["interrupts"]:
        L.append("Interruptions: %d" % st["interrupts"])
        L.append("")
    L.append("## Tool tally (%d calls, %d failed, %s result chars)" % (st["tool_calls"], st["failed_calls"], fmt_n(st["result_chars"])))
    L.append("")
    if st["tally"]:
        L.append("| tool | calls | failed calls | result chars |")
        L.append("|---|---:|---:|---:|")
        rows = sorted(st["tally"].items(), key=lambda kv: (-kv[1][0], kv[0]))
        for name, (n, f, ch) in rows[:15]:
            L.append("| %s | %d | %d | %s |" % (md_cell(name), n, f, fmt_n(ch)))
        if len(rows) > 15:
            L.append("| (%d more tools) | %d | %d | %s |" % (len(rows) - 15, sum(r[1][0] for r in rows[15:]), sum(r[1][1] for r in rows[15:]), fmt_n(sum(r[1][2] for r in rows[15:]))))
        L.append("")
    if st["commands"]:
        L.append("## Commands (%d shell calls)" % st["shell_calls"])
        L.append("")
        L.append("A shell call that chains programs (`a && b | c`) counts once for each program; failed calls, output chars and seconds are those of the whole shell call.")
        L.append("")
        L.append("| program | shell calls running it | as first program | failed calls | output chars | seconds |")
        L.append("|---|---:|---:|---:|---:|---:|")
        rows = sorted(st["commands"].items(), key=lambda kv: (-kv[1][0], -kv[1][2], kv[0]))
        for name, (n, f, ch, secs, timed, first) in rows[:15]:
            L.append("| %s | %d | %d | %d | %s | %s |" % (md_cell(name), n, first, f, fmt_n(ch), ("%d" % secs) if timed else "?"))
        if len(rows) > 15:
            L.append("| (%d more programs) | %d | %d | | | |" % (len(rows) - 15, sum(r[1][0] for r in rows[15:]), sum(r[1][5] for r in rows[15:])))
        L.append("")
    L.append("## Failed calls (%d; %d rerun blindly, %d rerun after a change)" % (len(st["fails"]), st["blind_retries"], st["reruns_after_change"]))
    L.append("")
    L.append("Blind retry: the identical call ran again with no edit or other state-changing call in between.")
    L.append("")

    def _rerun(f):
        if f["blind"]:
            return " (blind retry at [%d])" % f["rerun_at"]
        if f["after_change"]:
            return " (rerun at [%d] after a change)" % f["rerun_at"]
        return ""

    for f in st["fails"][:15]:
        L.append("- [%d] %s `%s`: %s%s" % (f["pos"], f["label"], head(f["inp"], 80).replace("`", "'"), head(f["error"], 200), _rerun(f)))
    if len(st["fails"]) > 15:
        L.append("- … %d more" % (len(st["fails"]) - 15))
    L.append("")
    reps = st["repeats"]
    reads = sorted(((p, v) for p, v in st["reads"].items() if v[0] >= 2), key=lambda kv: (-kv[1][0], -kv[1][1], kv[0]))
    L.append("## Repeats (identical calls; file reads)")
    L.append("")
    if not reps and not reads:
        L.append("none")
    for r in reps[:10]:
        L.append("- %d calls: %s `%s` (%s result chars; at %s)" % (r["count"], r["tool"], head(r["inp"], 90).replace("`", "'"), fmt_n(r["chars"]),
                                                          ", ".join(str(p) for p in r["positions"][:6]) + (" …" if len(r["positions"]) > 6 else "")))
    if len(reps) > 10:
        L.append("- … %d more repeated calls" % (len(reps) - 10))
    for p, (n, ch, poss) in reads[:10]:
        L.append("- file read %d times: %s (%s chars; at %s)" % (n, p, fmt_n(ch), ", ".join(str(x) for x in poss[:6])))
    L.append("")
    L.append("## Biggest results")
    L.append("")
    for size, i, it in st["biggest"]:
        call = None
        for j in range(i - 1, -1, -1):
            if items[j]["k"] == "call" and items[j].get("res") is it:
                call = items[j]
                break
        L.append("- [%d] %s chars from %s `%s`" % (i, fmt_n(size), it.get("tool"), head((call or {}).get("inp") or "", 90).replace("`", "'")))
    L.append("")
    L.append("## Final assistant message (tail)")
    L.append("")
    L.append(tail(flat(st["final_text"]), 400) or "(none)")
    if kids:
        L.append("")
        L.append("## Subagent prompts")
        L.append("")
        for k in kids[:12]:
            ks = by_id.get(k)
            if not ks:
                continue
            t = ks["stats"]["tasks"]
            L.append("- %s (%s, %s tokens): %s" % (k, md_cell(title_of(ks))[:60], fmt_n(ks["stats"]["tokens_total"]),
                                                   head(flat(t[0][1]["text"]), 300) if t else "(prompt not recorded)"))
    return "\n".join(L) + "\n"


def headline(parsed, scan):
    tops = [s for s in parsed if not s.get("is_subagent")]
    tot = {"in": 0, "cr": 0, "cw": 0, "out": 0}
    for s in parsed:
        for k in tot:
            tot[k] += s["stats"]["tokens"][k]
    calls = sum(s["stats"]["tool_calls"] for s in parsed)
    fails = sum(s["stats"]["failed_calls"] for s in parsed)
    costs = [s["meta"]["cost"] for s in parsed if s["meta"]["cost"] is not None]
    h = collections.OrderedDict()
    h["sessions"] = len(parsed)
    h["top_level_sessions"] = len(tops)
    h["subagent_sessions"] = len(parsed) - len(tops)
    h["tokens_total"] = sum(tot.values())
    h["tokens_uncached_input"] = tot["in"]
    h["tokens_cache_read"] = tot["cr"]
    h["tokens_cache_write"] = tot["cw"]
    h["tokens_output"] = tot["out"]
    h["median_tokens_per_session"] = median([s["stats"]["tokens_total"] for s in tops])
    h["median_uncached_input_per_session"] = median([s["stats"]["tokens"]["in"] for s in tops])
    h["median_cache_read_per_session"] = median([s["stats"]["tokens"]["cr"] for s in tops])
    h["median_cache_write_per_session"] = median([s["stats"]["tokens"]["cw"] for s in tops])
    h["median_output_per_session"] = median([s["stats"]["tokens"]["out"] for s in tops])
    h["median_human_prompts"] = median([s["stats"]["human_prompts"] for s in tops])
    h["median_tool_calls"] = median([s["stats"]["tool_calls"] for s in tops])
    h["tool_calls"] = calls
    h["failed_calls"] = fails
    h["failed_call_rate"] = (fails / calls) if calls else None
    h["compaction_share"] = (sum(1 for s in tops if s["stats"]["compactions"]) / len(tops)) if tops else None
    h["median_duration_min"] = (median([s["stats"]["wall_s"] for s in tops]) or 0) / 60.0 if tops else None
    h["median_active_min"] = (median([s["stats"]["active_s"] for s in tops]) or 0) / 60.0 if tops else None
    h["total_cost_usd"] = round(sum(costs), 2) if costs else None
    h["sessions_with_cost"] = len(costs)
    return h


METRIC_LABELS = collections.OrderedDict([
    ("sessions", "sessions"), ("top_level_sessions", "top-level sessions"), ("subagent_sessions", "subagent sessions"),
    ("tokens_total", "tokens, total"), ("tokens_uncached_input", "tokens, uncached input"),
    ("tokens_cache_read", "tokens, cache read"), ("tokens_cache_write", "tokens, cache write"), ("tokens_output", "tokens, output"),
    ("median_tokens_per_session", "median tokens per session"), ("median_uncached_input_per_session", "median uncached input"),
    ("median_cache_read_per_session", "median cache read"), ("median_cache_write_per_session", "median cache write"),
    ("median_output_per_session", "median output"), ("median_human_prompts", "median human prompts"),
    ("median_tool_calls", "median tool calls"), ("tool_calls", "tool calls"), ("failed_calls", "failed calls"),
    ("failed_call_rate", "failed-call rate"), ("compaction_share", "share of sessions with a compaction"),
    ("median_duration_min", "median duration (min, wall)"), ("median_active_min", "median active time (min)"),
    ("total_cost_usd", "total cost (USD, where recorded)"), ("sessions_with_cost", "sessions with recorded cost"),
])


def fmt_metric(k, v):
    if v is None:
        return "n/a"
    if k in ("failed_call_rate", "compaction_share"):
        return "%.1f%%" % (v * 100)
    if k.endswith("_min"):
        return "%.1f" % v
    if k == "total_cost_usd":
        return "$%.2f" % v
    if k.startswith("tokens") or "per_session" in k:
        return fmt_n(v)
    if isinstance(v, float):
        return ("%.1f" % v).rstrip("0").rstrip(".")
    return str(v)


def week_start(t):
    if t is None:
        return "?"
    d = datetime.datetime.fromtimestamp(t, datetime.timezone.utc).date()
    return (d - datetime.timedelta(days=d.weekday())).isoformat()


def by_harness(counter):
    return ", ".join("%s %s" % (k, "{:,}".format(v)) for k, v in sorted(counter.items(), key=lambda kv: (-kv[1], kv[0])) if v)


def group_row(lead, ss, harness=True):
    """Markdown row of per-group numbers shared by the week and tool/model tables."""
    tops_ = [x for x in ss if not x.get("is_subagent")]
    calls = sum(x["stats"]["tool_calls"] for x in ss)
    fails = sum(x["stats"]["failed_calls"] for x in ss)
    cells = list(lead) + [
        str(len(tops_)), str(len(ss) - len(tops_)), fmt_n(sum(x["stats"]["tokens_total"] for x in ss)),
        fmt_n(median([x["stats"]["tokens_total"] for x in tops_])) if tops_ else "n/a",
        str(sum(x["stats"]["human_prompts"] for x in tops_)),
        fmt_metric("x", median([x["stats"]["human_prompts"] for x in tops_])),
        ("%.1f%%" % (100.0 * fails / calls)) if calls else "n/a",
        ("%.0f%%" % (100.0 * sum(1 for x in tops_ if x["stats"]["compactions"]) / len(tops_))) if tops_ else "n/a",
    ]
    if harness:
        cells.append(by_harness(collections.Counter(x["tool"] for x in tops_)))
        return "| " + " | ".join(cells) + " |"
    return "| " + " | ".join(cells) + " |"


def render_summary(scan, h):
    parsed = scan.parsed
    tops = [s for s in parsed if not s.get("is_subagent")]
    L = ["# Agent session digest", ""]
    ident = scan.ident
    L.append("Repo: %s (name `%s`; remotes: %s). Window: sessions started %s to %s (--since %g --until %g days). Generated %s in %.1fs." % (
        ident["toplevel"], ident["name"], ", ".join(ident["remotes"]) or "none", fmt_ts(scan.t_from), fmt_ts(scan.t_to),
        scan.args.since, scan.args.until, fmt_ts(time.time()), scan.elapsed))
    L.append("")
    L.append("Positions like [123] index the trace printed by `session_digest.py show --out DIR SESSION_ID --from N --to N`.")
    L.append("")
    L.append("## Sources")
    L.append("")
    if not parsed:
        L.append("**No sessions matched this repo in the window.** Check --repo, widen --since, or see the per-store notes below.")
        L.append("")
    for name in list(scan.sources):
        d = scan.sources.get(name)
        found = "found" if d["found"] else ("not read" if any("not requested" in n for n in d["notes"]) else "not found")
        how = ", ".join("%s %d" % (k, v) for k, v in sorted(d["how"].items(), key=lambda kv: (-kv[1], kv[0])))
        L.append("- **%s** (%s): %s; sessions in digest: %d%s" % (name, d["location"], found, d["matched"], (" (matched by: %s)" % how) if how else ""))
        for k, v in sorted(d["skipped"].items()):
            if k.startswith("(included) "):
                L.append("  - %s: %d (threads kept in the digest, not skipped)" % (k[11:], v))
            else:
                L.append("  - skipped: %s: %d" % (k, v))
        for n in d["notes"]:
            L.append("  - %s" % n)
        if d.get("projects"):
            L.append("  - T3 projects: %s" % "; ".join(d["projects"]))
        for fdesc in d.get("files") or []:
            L.append("  - imported file: %s" % fdesc)
    stores = collections.Counter(s["store"] for s in parsed)
    L.append("- sessions per store: %s" % (", ".join("%s %d" % kv for kv in sorted(stores.items())) or "none"))
    L.append("- dedupe: a T3 thread that wraps a native Claude Code, Codex, OpenCode or Pi session is one session (store `t3+<native>`); content comes from the native transcript, title and lineage from T3. Threads whose transcript is missing are built from T3 tables (store `t3`): those have per-turn token totals only and no cost.")
    L.append("- Codex `exec` scripts: the commands and tool calls inside a script are the counted unit; the script wrapper is shown in traces but counted only when nothing inside it ran or it failed with no failing inner call.")
    pp = [s for s in parsed if s.get("match") == "path pattern"]
    if pp:
        L.append("- %d sessions were matched by path pattern only (cwd no longer exists, contains `/%s/`): %s" % (len(pp), ident["name"], ", ".join(sorted(s["id"][:8] for s in pp)[:30])))
    if scan.utility:
        ut = scan.utility_tokens
        L.append("- excluded: %d T3 text-generation helper sessions (commit message, branch, PR text, title), %s tokens in total" % (len(scan.utility), fmt_n(sum(ut.values()))))
    if scan.cut:
        L.append("- **--max-sessions %d cut %d older sessions** (newest kept, subagents kept with their parent)" % (scan.args.max_sessions, scan.cut))
    if scan.errors:
        L.append("- unreadable sessions skipped: %d (%s)" % (len(scan.errors), "; ".join(scan.errors[:5])))
    L.append("")
    L.append("## Headline metrics")
    L.append("")
    L.append("Totals cover all sessions; medians and shares cover top-level sessions (subagents excluded). Tokens are as recorded by each store; result sizes are characters, not tokens.")
    L.append("")
    L.append("| metric | value |")
    L.append("|---|---:|")
    for k, label in METRIC_LABELS.items():
        L.append("| %s | %s |" % (label, fmt_metric(k, h.get(k))))
    L.append("")
    weeks = {}
    for x in parsed:
        t = x["meta"]["start"] or x.get("start_hint")
        weeks.setdefault(week_start(t), []).append(x)
    L.append("## By week")
    L.append("")
    L.append("Weeks start on Monday (UTC). Sessions, medians and shares count top-level sessions; tokens and failed-call rate include subagents.")
    L.append("")
    L.append("| week start | sessions | subagent sessions | tokens | median tokens per session | human prompts | median human prompts | failed-call rate | compaction share | by harness (sessions) |")
    L.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---|")
    for wk in sorted(weeks):
        L.append(group_row([wk], weeks[wk]))
    L.append("")
    L.append("## By tool and model")
    L.append("")
    L.append("| tool | model | sessions | subagent sessions | tokens | median tokens per session | human prompts | median human prompts | failed-call rate | compaction share | median tool calls | median duration (min) | uncached in | cache read | cache write | output |")
    L.append("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    grp = {}
    for x in parsed:
        grp.setdefault((x["tool"], main_model(x)), []).append(x)
    for key in sorted(grp, key=lambda k: (-sum(x["stats"]["tokens_total"] for x in grp[k]), k)):
        ss = grp[key]
        tops_ = [x for x in ss if not x.get("is_subagent")]
        tk = {k: sum(x["stats"]["tokens"][k] for x in ss) for k in ("in", "cr", "cw", "out")}
        row = group_row([key[0], md_cell(key[1])], ss, harness=False)
        L.append(row + " %s | %s | %s | %s | %s | %s |" % (
            fmt_metric("x", median([x["stats"]["tool_calls"] for x in tops_])),
            ("%.1f" % (median([x["stats"]["wall_s"] for x in tops_]) / 60.0)) if median([x["stats"]["wall_s"] for x in tops_]) is not None else "n/a",
            fmt_n(tk["in"]), fmt_n(tk["cr"]), fmt_n(tk["cw"]), fmt_n(tk["out"])))
    L.append("")
    L.append("## Sessions by total tokens")
    L.append("")
    L.append("| id | tool | model | date | duration | human prompts | tool calls | failed calls | tokens | compactions | subagents | title |")
    L.append("|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|")
    rows = sorted(parsed, key=lambda s: (-s["stats"]["tokens_total"], s["id"]))
    kids = scan.children
    for s in rows[:60]:
        st = s["stats"]
        L.append("| %s | %s | %s | %s | %s | %d | %d | %d | %s | %d | %d | %s |" % (
            s["id"][:12] + ("*" if s.get("is_subagent") else ""), s["tool"], md_cell(main_model(s)), fmt_date(s["meta"]["start"] or s.get("start_hint")),
            fmt_dur(st["wall_s"]), st["human_prompts"], st["tool_calls"], st["failed_calls"], fmt_n(st["tokens_total"]),
            st["compactions"], len(kids.get(s["id"], [])), md_cell(head(one_line(title_of(s)), 60))))
    if len(rows) > 60:
        L.append("")
        L.append("(%d more sessions in scan.json; `*` marks a subagent session)" % (len(rows) - 60))
    else:
        L.append("")
        L.append("`*` marks a subagent session.")
    L.append("")
    L.append("## Across sessions")
    L.append("")
    L.append("`by harness` splits the calls column by the harness that ran them. A shell call that chains several programs counts once for each.")
    L.append("")
    cmd = {}
    for s in parsed:
        for name, (n, f, ch, secs, timed, first) in s["stats"]["commands"].items():
            e = cmd.setdefault(name, [set(), 0, 0, 0, 0.0, 0, collections.Counter(), 0])
            e[0].add(s["id"])
            e[1] += n
            e[2] += f
            e[3] += ch
            e[4] += secs
            e[5] += timed
            e[6][s["tool"]] += n
            e[7] += first
    L.append("### Top commands")
    L.append("")
    L.append("| program | sessions | shell calls running it | as first program | failed calls | output chars | seconds | by harness (calls) |")
    L.append("|---|---:|---:|---:|---:|---:|---:|---|")
    for name, e in sorted(cmd.items(), key=lambda kv: (-kv[1][1], kv[0]))[:20]:
        L.append("| %s | %d | %d | %d | %d | %s | %s | %s |" % (md_cell(name), len(e[0]), e[1], e[7], e[2], fmt_n(e[3]), ("%d" % e[4]) if e[5] else "?", by_harness(e[6])))
    L.append("")
    L.append("### Top failing commands and tools")
    L.append("")
    fl = {}
    for s in parsed:
        for f in s["stats"]["fails"]:
            e = fl.setdefault(f["label"], [set(), 0, 0, 0, "", collections.Counter()])
            e[0].add(s["id"])
            e[1] += 1
            e[2] += 1 if f["blind"] else 0
            e[3] += 1 if f["after_change"] else 0
            e[5][s["tool"]] += 1
            if not e[4]:
                e[4] = "%s [%d]: %s" % (s["id"][:8], f["pos"], head(f["error"], 120))
    L.append("| command or tool | sessions | failed calls | blind retries | reruns after a change | by harness (failed calls) | example |")
    L.append("|---|---:|---:|---:|---:|---|---|")
    for name, e in sorted(fl.items(), key=lambda kv: (-kv[1][1], kv[0]))[:15]:
        L.append("| %s | %d | %d | %d | %d | %s | %s |" % (md_cell(name), len(e[0]), e[1], e[2], e[3], by_harness(e[5]), md_cell(e[4])))
    L.append("")
    L.append("### Blind retry loops")
    L.append("")
    L.append("A failed call run again identically with no edit or state-changing call in between.")
    L.append("")
    L.append("| command or tool | sessions | blind retries | by harness (blind retries) |")
    L.append("|---|---:|---:|---|")
    for name, e in sorted(((k, v) for k, v in fl.items() if v[2]), key=lambda kv: (-kv[1][2], kv[0]))[:12]:
        bh = collections.Counter()
        ss_ = set()
        for s in parsed:
            for f in s["stats"]["fails"]:
                if f["label"] == name and f["blind"]:
                    bh[s["tool"]] += 1
                    ss_.add(s["id"])
        L.append("| %s | %d | %d | %s |" % (md_cell(name), len(ss_), e[2], by_harness(bh)))
    L.append("")
    L.append("### Most-read files")
    L.append("")
    rd = {}
    for s in parsed:
        for p, (n, ch, _) in s["stats"]["reads"].items():
            rel = p
            for r in scan.m.roots():
                if p.startswith(r + "/"):
                    rel = p[len(r) + 1:]
                    break
            e = rd.setdefault(rel, [set(), 0, 0, collections.Counter()])
            e[0].add(s["id"])
            e[1] += n
            e[2] += ch
            e[3][s["tool"]] += n
    L.append("| file (relative to its worktree) | sessions | reads | chars | by harness (reads) |")
    L.append("|---|---:|---:|---:|---|")
    for name, e in sorted(rd.items(), key=lambda kv: (-len(kv[1][0]), -kv[1][1], kv[0]))[:20]:
        L.append("| %s | %d | %d | %s | %s |" % (md_cell(name), len(e[0]), e[1], fmt_n(e[2]), by_harness(e[3])))
    L.append("")
    L.append("### Commands with the largest total output")
    L.append("")
    L.append("| program | sessions | shell calls running it | output chars | by harness (calls) |")
    L.append("|---|---:|---:|---:|---|")
    for name, e in sorted(cmd.items(), key=lambda kv: (-kv[1][3], kv[0]))[:12]:
        L.append("| %s | %d | %d | %s | %s |" % (md_cell(name), len(e[0]), e[1], fmt_n(e[3]), by_harness(e[6])))
    L.append("")
    L.append("### Tools with the largest total results")
    L.append("")
    tl = {}
    for s in parsed:
        for name, (n, f, ch) in s["stats"]["tally"].items():
            e = tl.setdefault(name, [set(), 0, 0, 0, collections.Counter()])
            e[0].add(s["id"])
            e[1] += n
            e[2] += f
            e[3] += ch
            e[4][s["tool"]] += n
    L.append("| tool | sessions | calls | failed calls | result chars | by harness (calls) |")
    L.append("|---|---:|---:|---:|---:|---|")
    for name, e in sorted(tl.items(), key=lambda kv: (-kv[1][3], kv[0]))[:12]:
        L.append("| %s | %d | %d | %d | %s | %s |" % (md_cell(name), len(e[0]), e[1], e[2], fmt_n(e[3]), by_harness(e[4])))
    L.append("")
    L.append("## Subagent use")
    L.append("")
    spawners = [s for s in tops if kids.get(s["id"]) or s["meta"]["spawned"]]
    sub_tok = sum(s["stats"]["tokens_total"] for s in parsed if s.get("is_subagent"))
    all_tok = sum(s["stats"]["tokens_total"] for s in parsed) or 1
    L.append("- %d of %d top-level sessions spawned subagents (%d subagent sessions in this digest, %d spawn calls in total)." % (
        len(spawners), len(tops), len(parsed) - len(tops), sum(s["meta"]["spawned"] for s in parsed)))
    L.append("- subagent sessions used %s tokens, %.1f%% of all tokens." % (fmt_n(sub_tok), 100.0 * sub_tok / all_tok))
    orphans = [s for s in parsed if s.get("is_subagent") and not s.get("parent")]
    if orphans:
        L.append("- %d subagent sessions have a parent outside this digest (outside the window or not matched)." % len(orphans))
    L.append("")
    L.append("## Suggested deep reads")
    L.append("")
    picks = collections.OrderedDict()

    def pick(lst, reason, n):
        c = 0
        for s in lst:
            if c >= n:
                break
            if s["id"] in picks:
                continue
            picks[s["id"]] = reason(s)
            c += 1

    pick(sorted(tops, key=lambda s: (-s["stats"]["tokens_total"], s["id"])), lambda s: "top by tokens (%s)" % fmt_n(s["stats"]["tokens_total"]), 3)
    pick(sorted([s for s in parsed if s["stats"]["failed_calls"]], key=lambda s: (-s["stats"]["failed_calls"], s["id"])), lambda s: "most failed calls (%d)" % s["stats"]["failed_calls"], 3)
    pick(sorted([s for s in tops if s["stats"]["human_prompts"]], key=lambda s: (-s["stats"]["human_prompts"], s["id"])), lambda s: "most human prompts (%d)" % s["stats"]["human_prompts"], 3)
    med = h.get("median_tokens_per_session") or 0
    pick(sorted(tops, key=lambda s: (abs(s["stats"]["tokens_total"] - med), s["id"])), lambda s: "near the median (%s tokens)" % fmt_n(s["stats"]["tokens_total"]), 2)
    for sid, reason in list(picks.items())[:12]:
        L.append("- `%s`: %s, sessions/%s.md" % (sid, reason, sid))
    if not picks:
        L.append("none (no sessions)")
    return drop_empty_tables("\n".join(L)) + "\n"


def drop_empty_tables(text):
    """Replace a table that has a header but no rows with 'none'."""
    lines = text.split("\n")
    res = []
    i = 0
    while i < len(lines):
        if (lines[i].startswith("| ") and i + 1 < len(lines) and lines[i + 1].startswith("|---")
                and (i + 2 >= len(lines) or not lines[i + 2].startswith("|"))):
            res.append("none")
            i += 2
            continue
        res.append(lines[i])
        i += 1
    return "\n".join(res)


def shingles(words, lo=3, hi=6):
    out_ = set()
    for n in range(lo, hi + 1):
        for i in range(len(words) - n + 1):
            out_.add(" ".join(words[i:i + n]))
    return out_


_WORD = re.compile(r"[^\W_]+(?:'[^\W_]+)?", re.U)


def _norm_line(line):
    return re.sub(r"\s+", " ", re.sub(r"\d+", "#", line.strip().lower()))


def _shape_pasted(line):
    """A line that looks copied rather than typed: very long, or mostly symbols, digits and paths."""
    t = line.strip()
    if len(t) >= 220:
        return True
    if len(t) < 16:
        return False
    other = sum(1 for ch in t if not (ch.isalpha() or ch.isspace()))
    return other / float(len(t)) >= 0.3


def split_prompts(prompts, min_sessions=3, win=3):
    """prompts: [(session id, pos, text)]. Returns typed text per prompt and recurring pasted blocks.

    A line is pasted when it sits in a run of `win` consecutive lines whose normalised form
    (lowercase, digits as #) appears in `min_sessions`+ sessions, or when its shape says so."""
    norm = []
    wsess = collections.defaultdict(set)
    lsess = collections.defaultdict(set)
    for sid, pos, text in prompts:
        lines = [l for l in (text or "").split("\n") if l.strip()]
        nl = [_norm_line(l) for l in lines]
        norm.append((sid, pos, lines, nl))
        for i in range(len(nl) - win + 1):
            wsess[tuple(nl[i:i + win])].add(sid)
        for x in nl:
            if len(x) >= 40:
                lsess[x].add(sid)
    recurring = {w for w, ss in wsess.items() if len(ss) >= min_sessions and sum(len(x) for x in w) >= 30}
    # for telling typed from pasted text a block or long line seen verbatim in 2+ sessions is enough
    seen_twice = {w for w, ss in wsess.items() if len(ss) >= 2 and sum(len(x) for x in w) >= 30}
    long_twice = {x for x, ss in lsess.items() if len(ss) >= 2}
    parent = {}

    def find(x):
        while parent.get(x, x) != x:
            parent[x] = parent.get(parent[x], parent[x])
            x = parent[x]
        return x

    typed, instances = [], []
    for sid, pos, lines, nl in norm:
        cover = [False] * len(lines)
        wins = []
        for i in range(len(nl) - win + 1):
            w = tuple(nl[i:i + win])
            if w in recurring:
                for j in range(i, i + win):
                    cover[j] = True
                wins.append((i, w))
        # one block instance per maximal covered run; windows inside it belong together
        j = 0
        while j < len(lines):
            if not cover[j]:
                j += 1
                continue
            k = j
            while k < len(lines) and cover[k]:
                k += 1
            ws = [w for i, w in wins if j <= i < k]
            for w in ws[1:]:
                parent[find(w)] = find(ws[0])
            instances.append((ws[0], sid, pos, lines[j:k]))
            j = k
        drop = list(cover)
        for i in range(len(nl) - win + 1):
            if tuple(nl[i:i + win]) in seen_twice:
                for j in range(i, i + win):
                    drop[j] = True
        typed.append((sid, pos, "\n".join(l for i, l in enumerate(lines)
                                           if not drop[i] and not _shape_pasted(l) and nl[i] not in long_twice)))
    blocks = {}
    for w0, sid, pos, blines in instances:
        e = blocks.setdefault(find(w0), {"sessions": set(), "examples": [], "excerpts": collections.Counter()})
        e["sessions"].add(sid)
        e["examples"].append((sid, pos))
        e["excerpts"][" / ".join(one_line(l) for l in blines[:4])] += 1
    out_ = []
    for e in blocks.values():
        ex = sorted(e["excerpts"].items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
        firsts = []
        for sid, pos in sorted(e["examples"]):
            if sid not in [x[0] for x in firsts]:
                firsts.append((sid, pos))
        out_.append({"sessions": e["sessions"], "excerpt": ex, "examples": firsts[:2]})
    out_.sort(key=lambda b: (-len(b["sessions"]), b["excerpt"]))
    return typed, out_


def recurring_phrases(typed, lo=3, hi=6, min_sessions=3, n_common=60, cap=40):
    """3-6 word shingles of typed text found in min_sessions+ sessions, without filler and overlap."""
    df = collections.Counter()
    words_of = []
    for sid, pos, text in typed:
        t = re.sub(r"\[[^\]\n]{0,200}\]", " ", text)
        t = re.sub(r"\S+://\S+|\S*[/\\]\S*[/\\]\S*", " ", t)  # URLs and paths are pasted, not phrasing
        ws = [w.lower() for w in _WORD.findall(t) if not w.isdigit()]
        words_of.append((sid, ws))
        df.update(set(ws))
    # the corpus's own most common words (works for any language)
    common = {w for w, _ in sorted(df.items(), key=lambda kv: (-kv[1], kv[0]))[:n_common]}
    occ = collections.defaultdict(set)
    for sid, ws in words_of:
        for x in shingles(ws, lo, hi):
            occ[x].add(sid)
    cand = {x: frozenset(ids) for x, ids in occ.items() if len(ids) >= min_sessions and not all(w in common for w in x.split())}
    # within one session set keep the longest phrases, joining ones that overlap at the edges
    groups = collections.defaultdict(list)
    for x, ids in cand.items():
        groups[ids].append(x)
    merged = []
    for ids, xs in groups.items():
        xs = sorted(set(xs), key=lambda x: (-len(x.split()), x))
        kept = []
        for x in xs:
            if not any((" " + x + " ") in (" " + y + " ") for y in kept):
                kept.append(x)
        changed = True
        while changed and len(kept) > 1:
            changed = False
            for i in range(len(kept)):
                for j in range(len(kept)):
                    if i == j:
                        continue
                    a, b = kept[i].split(), kept[j].split()
                    for k in range(min(len(a), len(b)) - 1, 1, -1):
                        if a[-k:] == b[:k]:
                            kept[i] = " ".join(a + b[k:])
                            del kept[j]
                            changed = True
                            break
                    if changed:
                        break
                if changed:
                    break
        merged.extend((x, ids) for x in kept)
    # drop a phrase contained in a longer one found in at least as many sessions; rank by
    # sessions x words outside the common list, so content-bearing asks come before filler
    def score(kv):
        return len(kv[1]) * sum(1 for w in kv[0].split() if w not in common)
    merged.sort(key=lambda kv: (-len(kv[1]), -len(kv[0].split()), kv[0]))
    pre = []
    for x, ids in merged:
        if any((" " + x + " ") in (" " + y + " ") and len(yids) >= len(ids) for y, yids in pre):
            continue
        pre.append((x, ids))
    merged = sorted(pre, key=lambda kv: (-len(kv[1]), -score(kv), kv[0]))
    res = []
    for x, ids in merged:
        if any((" " + x + " ") in (" " + y + " ") and len(yids) >= len(ids) for y, yids in res):
            continue
        res.append((x, ids))
        if len(res) >= cap:
            break
    return res, common


def render_prompts(scan):
    parsed = [s for s in scan.parsed if not s.get("is_subagent")]
    parsed.sort(key=lambda s: ((s["meta"]["start"] or s.get("start_hint") or 0), s["id"]))
    prompts = [(s["id"], i, it["text"]) for s in parsed for i, it in enumerate(s["items"]) if it["k"] == "human"]
    typed, blocks = split_prompts(prompts)
    phrases, common = recurring_phrases(typed)
    L = ["# Human prompts", ""]
    L.append("Subagent sessions and agent-written prompts are excluded. Positions index `show` output. Count any phrase exactly with `session_digest.py count --out DIR PATTERN`.")
    L.append("")
    L.append("## Recurring phrases")
    L.append("")
    L.append("From typed text only (pasted blocks, log-like lines, lines seen verbatim in other sessions, URLs and paths removed). Phrases made only of the %d most common words in these prompts are dropped; overlapping phrases found in the same sessions are merged. Most sessions first." % len(common))
    L.append("")
    if not phrases:
        L.append("none (no 3-6 word phrase appears in 3 or more sessions)")
    for x, ids in phrases:
        ws = x.split()
        L.append("- \"%s\": %d sessions (e.g. %s)" % (" ".join(ws[:14]) + (" …" if len(ws) > 14 else ""), len(ids), ", ".join(sorted(ids)[:2])))
    L.append("")
    L.append("## Recurring pasted blocks")
    L.append("")
    L.append("Runs of 3+ lines pasted into prompts of 3 or more sessions (digits ignored when comparing).")
    L.append("")
    if not blocks:
        L.append("none")
    for bl in blocks[:20]:
        L.append("- %d sessions: \"%s\" (e.g. %s)" % (len(bl["sessions"]), head(bl["excerpt"], 160),
                                                    ", ".join("%s [%d]" % e for e in bl["examples"])))
    L.append("")
    L.append("## Prompts by session")
    for s in parsed:
        hs = [(i, it) for i, it in enumerate(s["items"]) if it["k"] == "human"]
        if not hs:
            continue
        L.append("")
        L.append("### %s · %s · %s · %s" % (fmt_date(s["meta"]["start"] or s.get("start_hint")), s["tool"], s["id"], md_cell(head(one_line(title_of(s)), 70))))
        L.append("")
        for i, it in hs:
            L.append("- [%d] %s" % (i, head(flat(it["text"]), 400)))
    return "\n".join(L) + "\n"


def session_index(s):
    st, meta = s["stats"], s["meta"]
    natives = [[k, nid, p] for k, nid, p in s.get("natives", [])]
    return collections.OrderedDict([
        ("id", s["id"]), ("tool", s["tool"]), ("store", s["store"]), ("provider", s.get("provider")),
        ("sources", s["sources"]), ("natives", natives), ("t3_thread_id", s.get("t3_thread_id")),
        ("title", title_of(s)), ("models", dict(sorted(meta["models"].items()))), ("model", main_model(s)),
        ("start", meta["start"] or s.get("start_hint")), ("end", meta["end"]), ("wall_s", st["wall_s"]), ("active_s", st["active_s"]),
        ("cwd", s.get("cwd") or meta.get("cwd")), ("branch", s.get("branch") or meta.get("branch")), ("match", s.get("match")),
        ("is_subagent", bool(s.get("is_subagent"))), ("parent", s.get("parent")), ("parent_ref", s.get("parent_ref")),
        ("agent_created", bool(s.get("agent_created"))),
        ("human_prompts", st["human_prompts"]), ("t3_human_prompts", meta.get("t3_human")), ("tool_calls", st["tool_calls"]),
        ("failed_calls", st["failed_calls"]), ("result_chars", st["result_chars"]), ("interrupts", st["interrupts"]),
        ("tokens", st["tokens"]), ("tokens_total", st["tokens_total"]), ("peak_ctx", meta["peak_ctx"]),
        ("compactions", st["compactions"]), ("cost_usd", meta["cost"]), ("spawn_calls", meta["spawned"]),
        ("usage_incomplete_turns", meta["usage_incomplete"]), ("malformed_lines", meta["bad_lines"]), ("items", len(s["items"])),
        ("digest", "sessions/%s.md" % s["id"]),
    ])


def cmd_scan(args):
    if not os.path.isdir(args.repo):
        sys.exit("--repo %s is not a directory" % args.repo)
    scan = Scan(args)
    scan.run()
    parsed = scan.parsed
    by_id = {s["id"]: s for s in parsed}
    children = collections.defaultdict(list)
    for s in parsed:
        if s.get("parent") in by_id:
            children[s["parent"]].append(s["id"])
    scan.children = children
    by_id["_children"] = children
    outdir = os.path.abspath(args.out)
    os.makedirs(os.path.join(outdir, "sessions"), exist_ok=True)
    for s in parsed:
        write_file(os.path.join(outdir, "sessions", s["id"] + ".md"), render_session(s, by_id))
    h = headline(parsed, scan)
    write_file(os.path.join(outdir, "summary.md"), render_summary(scan, h))
    write_file(os.path.join(outdir, "prompts.md"), render_prompts(scan))
    idx = collections.OrderedDict([
        ("version", VERSION), ("generated_at", time.time()), ("elapsed_s", round(scan.elapsed, 2)),
        ("repo", scan.ident), ("window", {"since_days": args.since, "until_days": args.until, "from": scan.t_from, "to": scan.t_to}),
        ("tools", sorted(scan.tools)), ("max_sessions", args.max_sessions), ("cut_by_cap", scan.cut),
        ("sources", {k: {"found": v["found"], "location": v["location"], "matched": v["matched"], "how": dict(sorted(v["how"].items())),
                         "skipped": dict(sorted(v["skipped"].items())), "notes": v["notes"]} for k, v in scan.sources.items()}),
        ("utility_sessions", len(scan.utility)), ("utility_tokens", scan.utility_tokens), ("errors", scan.errors),
        ("headline", h),
        ("sessions", [session_index(s) for s in sorted(parsed, key=lambda s: (-(s["meta"]["start"] or s.get("start_hint") or 0), s["id"]))]),
    ])
    write_file(os.path.join(outdir, "scan.json"), json.dumps(redact_obj(idx), indent=1, ensure_ascii=False, sort_keys=False), raw=True)
    stores = collections.Counter(("t3" if s["store"].startswith("t3") else s["store"]) for s in parsed)
    write_cache(os.path.join(outdir, CACHE_NAME), parsed)
    out(os.path.join(outdir, "summary.md"))
    out("sessions: %d (%d top-level, %d subagent); by store: %s%s" % (h["sessions"], h["top_level_sessions"], h["subagent_sessions"],
                                                                       ", ".join("%s %d" % kv for kv in sorted(stores.items())) or "none",
                                                                       ("; WARNING --max-sessions %d cut %d older sessions" % (args.max_sessions, scan.cut)) if scan.cut else ""))
    out("tokens: %s total = uncached in %s + cache read %s + cache write %s + output %s" % (
        fmt_n(h["tokens_total"]), fmt_n(h["tokens_uncached_input"]), fmt_n(h["tokens_cache_read"]), fmt_n(h["tokens_cache_write"]), fmt_n(h["tokens_output"])))
    out("median per top-level session: %s tokens, %s human prompts, %s tool calls, %s min" % (
        fmt_metric("median_tokens_per_session", h["median_tokens_per_session"]), fmt_metric("x", h["median_human_prompts"]),
        fmt_metric("x", h["median_tool_calls"]), fmt_metric("median_duration_min", h["median_duration_min"])))
    out("failed-call rate %s (%d of %d); sessions with a compaction %s" % (
        fmt_metric("failed_call_rate", h["failed_call_rate"]), h["failed_calls"], h["tool_calls"], fmt_metric("compaction_share", h["compaction_share"])))
    out("cost where recorded: %s over %d sessions; scan took %.1fs" % (fmt_metric("total_cost_usd", h["total_cost_usd"]), h["sessions_with_cost"], scan.elapsed))


# --------------------------------------------------------------------------
# show / compare


CACHE_NAME = "items.jsonl.gz"
CACHE_RESULT = 600  # chars of each tool result kept for `count --in results`


def write_cache(path, parsed):
    """Compact, redacted copy of what `count` searches: full human prompts, assistant text
    (head and tail), counted calls (tool + short input) and results (first KEEP_RESULT chars + size)."""
    with gzip.open(path, "wt", encoding="utf-8", compresslevel=6) as f:
        for x in sorted(parsed, key=lambda s: ((s["meta"]["start"] or s.get("start_hint") or 0), s["id"])):
            rows = []
            for i, it in enumerate(x["items"]):
                k = it["k"]
                if k == "human":
                    rows.append([i, "p", it["text"]])
                elif k == "asst":
                    rows.append([i, "a", it["text"]])
                elif k == "call" and it.get("counted", True):
                    rows.append([i, "c", "%s %s" % (it["tool"], it.get("inp") or "")])
                elif k == "res" and it.get("counted", True):
                    rows.append([i, "r", (it.get("text") or "")[:CACHE_RESULT], it.get("size", 0)])
            t = x["meta"]["start"] or x.get("start_hint")
            rec = {"id": x["id"], "tool": x["tool"], "model": main_model(x), "week": week_start(t), "start": t,
                   "sub": bool(x.get("is_subagent")), "items": rows}
            f.write(json.dumps(redact_obj(rec), ensure_ascii=False) + "\n")


def cmd_count(args):
    path = os.path.join(args.out, CACHE_NAME)
    if not os.path.exists(path):
        sys.exit("%s not found: run `scan --out %s` with this version first" % (path, args.out))
    try:
        rx = re.compile(args.pattern, re.I if args.ignore_case else 0)
    except re.error as e:
        sys.exit("bad PATTERN: %s" % e)
    kinds = {"prompts": "p", "calls": "c", "results": "r", "assistant": "a", "all": "pcra"}[args.in_]
    total, matched = set(), set()
    buckets = collections.OrderedDict()
    occ_total, chars_total, examples = 0, 0, []
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            if rec["sub"] and not args.include_subagents:
                continue
            b = {"week": rec["week"], "tool": rec["tool"], "model": rec["model"], "none": "all"}[args.by]
            e = buckets.setdefault(b, [0, 0, 0, 0])
            e[1] += 1
            total.add(rec["id"])
            hit = False
            for row in rec["items"]:
                if row[1] not in kinds:
                    continue
                n = sum(1 for _ in rx.finditer(row[2]))
                if not n:
                    continue
                hit = True
                e[2] += n
                occ_total += n
                if row[1] == "r":
                    e[3] += row[3]
                    chars_total += row[3]
                if len(examples) < args.examples:
                    m = rx.search(row[2])
                    a = max(0, m.start() - 40)
                    examples.append((rec["id"], row[0], {"p": "prompt", "c": "call", "r": "result", "a": "assistant"}[row[1]],
                                     one_line(row[2][a:m.end() + 60])))
            if hit:
                e[0] += 1
                matched.add(rec["id"])
    scope = "top-level sessions" + (" and subagents" if args.include_subagents else "")
    share = (100.0 * len(matched) / len(total)) if total else 0.0
    out("pattern /%s/ in %s: %d of %d %s (%.1f%%), %d occurrences%s" % (
        args.pattern, args.in_, len(matched), len(total), scope, share, occ_total,
        (", %s result chars" % fmt_n(chars_total)) if "r" in kinds else ""))
    if args.by != "none":
        out("")
        hdr = "| %s | sessions matched | sessions | share | occurrences |%s" % (args.by, " result chars |" if "r" in kinds else "")
        out(hdr)
        out("|---|---:|---:|---:|---:|%s" % ("---:|" if "r" in kinds else ""))
        for b in sorted(buckets, key=lambda k: (k if args.by == "week" else (-buckets[k][0], k))):
            e = buckets[b]
            out("| %s | %d | %d | %.1f%% | %d |%s" % (b, e[0], e[1], (100.0 * e[0] / e[1]) if e[1] else 0, e[2],
                                                    (" %s |" % fmt_n(e[3])) if "r" in kinds else ""))
    if examples:
        out("")
        out("examples (session, position; `show --out %s ID --from N --to N`):" % args.out)
        for sid, pos, kind, ex in examples:
            out("- %s [%d] %s: %s" % (sid, pos, kind, head(ex, 160)))


def load_index(path):
    p = path
    if os.path.isdir(p):
        p = os.path.join(p, "scan.json")
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError) as e:
        sys.exit("cannot read %s: %s" % (p, e))


def cmd_show(args):
    idx = load_index(args.out)
    sid = args.session_id
    cands = [s for s in idx["sessions"] if s["id"] == sid] or [s for s in idx["sessions"] if s["id"].startswith(sid) or (s.get("t3_thread_id") or "") == sid]
    if not cands:
        sys.exit("no session matches %r in %s" % (sid, args.out))
    if len(cands) > 1:
        sys.exit("ambiguous id %r: %s" % (sid, ", ".join(s["id"] for s in cands[:10])))
    s = cands[0]
    conn = None
    db = os.path.join(T3_HOME, "userdata", "statev2.sqlite")
    agent_texts, t3_users = set(), None
    if s.get("t3_thread_id") and os.path.exists(db):
        conn = t3_connect(db)
        t3_users = t3_thread_user_messages(conn, s["t3_thread_id"])
        agent_texts = {agent_key(m.get("text") or "") for m in t3_users if m.get("createdBy") != "user"}
    sess = {"natives": [tuple(n) for n in s.get("natives") or []], "t3_thread_id": s.get("t3_thread_id"),
            "is_subagent": s.get("is_subagent")}
    global KEEP_RESULT
    KEEP_RESULT = max(KEEP_RESULT, args.width)
    items, meta = parse_sources(sess, conn, agent_texts, t3_users, _Ctx())
    rx = re.compile(args.grep, re.I) if args.grep else None
    lo = args.from_ if args.from_ is not None else 0
    hi = args.to if args.to is not None else len(items) - 1
    out("# %s · %s · %s · %d items (showing %d-%d)" % (s["id"], s["tool"], head(s.get("title") or "", 60), len(items), lo, min(hi, len(items) - 1)))
    for i in range(max(0, lo), min(hi, len(items) - 1) + 1):
        line = item_line(i, items[i], args.width)
        if rx and not rx.search(line):
            continue
        out(line)


def cmd_format(args):
    sys.stdout.write(IMPORT_SPEC + "\nExample (one session, six lines):\n\n" + IMPORT_EXAMPLE)


def cmd_compare(args):
    a, b = load_index(args.a), load_index(args.b)
    ha, hb = a.get("headline", {}), b.get("headline", {})

    def win(i):
        w = i.get("window", {})
        return "%s..%s" % (fmt_date(w.get("from")), fmt_date(w.get("to")))

    out("| metric | A (%s) | B (%s) | change |" % (win(a), win(b)))
    out("|---|---:|---:|---:|")
    for k, label in METRIC_LABELS.items():
        va, vb = ha.get(k), hb.get(k)
        if va is None or vb is None:
            ch = "n/a"
        elif va == 0:
            ch = "n/a" if vb == 0 else "new"
        else:
            ch = "%+.1f%%" % ((vb - va) * 100.0 / va)
        out("| %s | %s | %s | %s |" % (label, fmt_metric(k, va), fmt_metric(k, vb), ch))


# --------------------------------------------------------------------------


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="session_digest.py",
        description="Digest a repo's past AI coding-agent sessions (Claude Code, Codex, OpenCode, Pi, T3 Code, or any harness via --import) without reading raw transcripts. "
                    "All stores are opened read-only.")
    sub = ap.add_subparsers(dest="cmd")
    sub.required = True

    sp = sub.add_parser("scan", help="build summary.md, prompts.md, sessions/*.md and scan.json",
                        description="Find the sessions that belong to a git repo (its toplevel, worktrees, remotes and folder name) "
                                    "in ~/.claude/projects, ~/.codex, ~/.local/share/opencode/opencode.db, ~/.pi/agent/sessions and "
                                    "~/.t3/userdata/statev2.sqlite (plus --import files), then write the digest into --out. "
                                    "A session belongs to the window when it started inside it. Missing stores are reported and skipped. "
                                    "Env overrides: CLAUDE_CONFIG_DIR, CODEX_HOME, T3_HOME, OPENCODE_DB, PI_SESSIONS_DIR.")
    sp.add_argument("--repo", default=".", metavar="PATH", help="path inside the repo (default: current directory; its git toplevel is used)")
    sp.add_argument("--since", type=float, default=30, metavar="DAYS", help="window start, days ago (default 30)")
    sp.add_argument("--until", type=float, default=0, metavar="DAYS", help="window end, days ago (default 0 = now)")
    sp.add_argument("--tools", default=",".join(TOOL_NAMES), metavar="LIST", help="comma list of stores to read: %s (default all)" % ",".join(TOOL_NAMES))
    sp.add_argument("--import", dest="imports", action="append", metavar="FILE_OR_DIR",
                    help="also read sessions in the normalised JSONL format (see `session_digest.py format`); repeatable")
    sp.add_argument("--max-sessions", type=int, default=0, metavar="N", help="keep at most N sessions, newest first, subagents with their parent (default 0 = no cap)")
    sp.add_argument("--out", required=True, metavar="DIR", help="output directory (created if missing)")
    sp.set_defaults(func=cmd_scan)

    sh = sub.add_parser("show", help="print a compact numbered trace of one session",
                        description="Print one line per item of a session: HUMAN prompt, ASSISTANT text, CALL (tool and short input, "
                                    "duration), RESULT (size, ERROR flag, first chars), plus INJECTED / AGENT-PROMPT / COMPACTION / "
                                    "INTERRUPT lines. Numbers are the positions used in the digest files. Re-reads the original store.")
    sh.add_argument("--out", required=True, metavar="DIR", help="directory of a previous scan (or its scan.json)")
    sh.add_argument("session_id", help="session id or a unique prefix of it (a T3 thread id also works)")
    sh.add_argument("--from", dest="from_", type=int, metavar="N", help="first position to print")
    sh.add_argument("--to", type=int, metavar="N", help="last position to print")
    sh.add_argument("--grep", metavar="REGEX", help="only print lines matching this regex (case-insensitive), e.g. 'HUMAN|ERROR'")
    sh.add_argument("--width", type=int, default=200, metavar="CHARS", help="truncate each line to this many chars (default 200)")
    sh.set_defaults(func=cmd_show)

    ct = sub.add_parser("count", help="count a regex across a scan's sessions, by week, tool or model",
                        description="Count PATTERN (a Python regex) exactly across the sessions of a previous scan, using the cache "
                                    "scan writes (items.jsonl.gz); no store is re-read. prompts = full human prompt text; calls = tool name "
                                    "plus the short input (the shell command for shell tools); results = the first %d chars of each "
                                    "tool result (sizes are full); assistant = assistant text (head and tail of long messages)." % CACHE_RESULT)
    ct.add_argument("--out", required=True, metavar="DIR", help="directory of a previous scan")
    ct.add_argument("pattern", metavar="PATTERN", help="regular expression")
    ct.add_argument("--in", dest="in_", default="prompts", choices=["prompts", "calls", "results", "assistant", "all"], help="what to search (default prompts)")
    ct.add_argument("--by", default="week", choices=["week", "tool", "model", "none"], help="bucket the table by (default week)")
    ct.add_argument("--ignore-case", action="store_true", help="case-insensitive match")
    ct.add_argument("--examples", type=int, default=5, metavar="N", help="print N example positions (default 5)")
    ct.add_argument("--include-subagents", action="store_true", help="also count subagent sessions (default: top-level only)")
    ct.set_defaults(func=cmd_count)

    fm = sub.add_parser("format", help="print the --import JSONL format with an example",
                        description="Print the normalised session format read by `scan --import`, so a converter for any harness can be written from it.")
    fm.set_defaults(func=cmd_format)

    cp = sub.add_parser("compare", help="before/after table of headline metrics from two scans",
                        description="Print a markdown table of the headline metrics of scan A and scan B with the change in percent "
                                    "(B relative to A). Accepts scan.json paths or scan output directories.")
    cp.add_argument("a", help="A/scan.json (before)")
    cp.add_argument("b", help="B/scan.json (after)")
    cp.set_defaults(func=cmd_compare)

    args = ap.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
