# Fix for Jujutsu (jj) Shell Error

## Problem
You're experiencing a shell parsing error when running `jj` commands:
```
-n: -c: line 0: unexpected EOF while looking for matching `"'
-n: -c: line 1: syntax error: unexpected end of file
```

## Temporary Solution
I've created a wrapper script `jj-wrapper.sh` that runs jj with a clean environment. Use it like:
```bash
./jj-wrapper.sh status
./jj-wrapper.sh log
./jj-wrapper.sh diff
```

## Permanent Solutions

### Option 1: Add an alias to your shell
Add this to your `~/.zshrc`:
```bash
alias jj='env -i PATH="$PATH" HOME="$HOME" USER="$USER" TERM="$TERM" /opt/homebrew/bin/jj'
```

### Option 2: Debug the actual issue
The error suggests there's a shell hook or prompt command that's interfering with jj. This could be:

1. **Powerlevel10k prompt issue**: Your complex prompt might be interfering. Try temporarily disabling it:
   ```bash
   # Temporarily use a simple prompt
   PS1='%n@%m %~ %# '
   ```

2. **Shell integration issue**: Check if you have any shell integrations that might be causing problems:
   ```bash
   # Check for problematic hooks
   grep -E "precmd|preexec|chpwd" ~/.zshrc
   ```

3. **Jujutsu configuration**: Check if there's a problematic jj configuration:
   ```bash
   cat ~/.config/jj/config.toml
   ```

## What the wrapper does
The wrapper script runs jj with a minimal environment, preserving only essential variables:
- PATH (for finding executables)
- HOME (for config files)
- USER (for identity)
- TERM (for terminal capabilities)

This bypasses any shell customizations that might be causing the parsing error.
