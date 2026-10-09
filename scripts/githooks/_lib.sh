# Sourced by every shim in this directory (not a hook itself). INSTALLED layout (see
# scripts/install_git_hooks.py): <git-common-dir>/blarai-hooks/{githooks,hooks}; the install record
# is <git-common-dir>/blarai-install.json. Nothing here is read from any working tree or branch.
# Shell builtins only on the hot paths: git calls reference-transaction up to a dozen times per
# command and every external process costs ~0.1-0.3 s on Windows.
# Exported shell functions in the caller's environment could replace any builtin or command used below; unset is a
# special builtin (found before functions in the POSIX mode sh runs in), so it runs first.
unset -f '[' test echo printf read cd pwd command type git sed tr cat sha256sum true false exec 2>/dev/null
hook_name=${0##*/}
here=$(cd "${0%/*}" && pwd)
inst=$(cd "$here/.." && pwd)
common=$(cd "$here/../.." && pwd)
_nl='
'

# _rec_get <key>: value of the first `"<key>": "<value>"` line of the install record.
_rec_get() {
    _rv=
    [ -f "$common/blarai-install.json" ] || return 1
    _pat="\"$1\": \""
    while IFS= read -r _rl || [ -n "$_rl" ]; do
        case "$_rl" in
            *"$_pat"*) _rv=${_rl#*"$_pat"}; _rv=${_rv%%\"*}; return 0 ;;
        esac
    done < "$common/blarai-install.json"
    return 1
}

# Every installed hook file must equal the recorded hash; none missing, none extra.
verify_install() {
    _rec_get hook_count_str || { echo "BLOCKED: the install record is missing or unreadable ($common/blarai-install.json); run: python scripts/install_git_hooks.py --update" >&2; return 1; }
    _want_n=$_rv
    set -- "$here"/* "$inst"/hooks/*
    if [ "$#" -ne "$_want_n" ]; then
        echo "BLOCKED: $# hook files are installed but $_want_n are recorded; run: python scripts/install_git_hooks.py --check, then --update (the lead)" >&2
        return 1
    fi
    _hs=$(git hash-object --no-filters -- "$@" 2>/dev/null) || { echo "BLOCKED: cannot hash the installed hook files." >&2; return 1; }
    for _f in "$@"; do
        _h=${_hs%%"$_nl"*}
        case "$_hs" in *"$_nl"*) _hs=${_hs#*"$_nl"} ;; esac
        _key=${_f#"$inst"/}
        _rec_get "$_key" || { echo "BLOCKED: $_key is installed but not recorded." >&2; return 1; }
        if [ "$_h" != "$_rv" ]; then
            echo "BLOCKED: installed $_key differs from the install record; the git-native guard will not run edited code. Run: python scripts/install_git_hooks.py --check, then --update (the lead)" >&2
            return 1
        fi
    done
    return 0
}

_load_prev() {
    prev=
    [ -f "$common/blarai-previous-hooks" ] || return 1
    IFS= read -r prev < "$common/blarai-previous-hooks"
    [ -n "$prev" ] || return 1
    if [ "$prev" = "@default" ]; then prev="$common/hooks"; fi
    case "$prev" in *\\*) prev=$(printf '%s' "$prev" | tr '\\' '/') ;; esac
    [ -d "$prev" ] || return 1
    [ "$(cd "$prev" && pwd)" = "$here" ] && return 1
    return 0
}

# Hooks that read stdin: keep it in $stdin_data so our logic and the previous hook both see it.
capture_stdin() {
    stdin_data=
    _cr=$(printf '\r')
    while IFS= read -r _line || [ -n "$_line" ]; do
        _line=${_line%"$_cr"}
        if [ -z "$stdin_data" ]; then stdin_data=$_line; else stdin_data="$stdin_data
$_line"; fi
    done
}

chain_previous() {
    _load_prev || return 0
    _target="$prev/$hook_name"
    [ -f "$_target" ] || return 0
    if [ "${stdin_data+x}" = x ]; then
        printf '%s\n' "$stdin_data" | "$_target" "$@"
    else
        "$_target" "$@"
    fi
}

# _sha256_of <file>: prints the lowercase sha256 of a file; returns 1 (fail closed) when the system's sha256sum
# is missing or its output is not a 64-hex digest. Only `command -p` (the system default path, never the
# caller's PATH or environment) is consulted: no fallback tool can be chosen by the caller.
_sha256_of() {
    _sv=
    if command -p sha256sum /dev/null >/dev/null 2>&1; then
        _sv=$(command -p sha256sum -- "$1" 2>/dev/null) || return 1
        _sv=${_sv%% *}
    else
        return 1
    fi
    case "$_sv" in ""|*[!0-9a-f]*) return 1 ;; esac
    [ "${#_sv}" -eq 64 ] || return 1
    printf '%s' "$_sv"
}

# Our python guards run from the INSTALLED copy with the BASE interpreter recorded at install (full path +
# sha256, verified here before it runs), as `python -I -S -B`: never found on PATH, ignoring PYTHON* and
# sitecustomize, and allow only on the affirmative token.
run_guard() {   # run_guard <script> [args...]
    _guard="$inst/hooks/$1"; shift
    if [ ! -f "$_guard" ]; then
        echo "BLOCKED: git-native guard script missing ($_guard). Run: python scripts/install_git_hooks.py --update" >&2
        return 1
    fi
    # The BASE interpreter by the full path recorded at install (never a venv launcher, so pyvenv.cfg is
    # irrelevant), its sha256 verified here BEFORE it runs.
    _rec_get base_interpreter; _py=$_rv
    _rec_get base_interpreter_sha256; _pysha=$_rv
    if [ -z "$_py" ] || [ -z "$_pysha" ] || [ ! -f "$_py" ]; then
        echo "BLOCKED: the recorded base python ($_py) is missing; run: python scripts/install_git_hooks.py --update" >&2
        return 1
    fi
    _have=$(_sha256_of "$_py") || { echo "BLOCKED: the system sha256sum is not available, so the python cannot be verified." >&2; return 1; }
    if [ "$_have" != "$_pysha" ]; then
        echo "BLOCKED: the recorded base python ($_py) changed; run: python scripts/install_git_hooks.py --check, then --update (the lead)" >&2
        return 1
    fi
    _gsha=$(_sha256_of "$_guard") || { echo "BLOCKED: cannot hash the guard script." >&2; return 1; }
    # Affirmative proof: the guard allows ONLY by printing this token (with the sha256 of the script it ran,
    # computed here independently). An exit 0 without it (a fake python, a replaced guard) is a refusal.
    if [ "${stdin_data+x}" = x ]; then
        _out=$(printf '%s\n' "$stdin_data" | "$_py" -I -S -B "$_guard" "$@")
    else
        _out=$("$_py" -I -S -B "$_guard" "$@")
    fi
    _grc=$?
    if [ "$_grc" -ne 0 ]; then
        if [ -n "$_out" ]; then echo "$_out" >&2; fi
        return 1
    fi
    if [ "$_out" != "BLARAI-GUARD-OK $_gsha" ]; then
        echo "BLOCKED: the guard exited 0 without the affirmative token for $_guard; refusing (a replaced python or guard cannot be trusted to say yes)." >&2
        return 1
    fi
    return 0
}

passthrough() {
    case "$hook_name" in post-rewrite|pre-push) capture_stdin ;; esac
    chain_previous "$@"
    exit $?
}
