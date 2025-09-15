# Jujutsu (jj) Commands Reference

This is a comprehensive reference of Jujutsu (jj) commands based on version 0.32.0 documentation.

## Important Notes
- The CLI reference is experimental and automatically generated
- Use `jj help <COMMAND>` for the most authoritative documentation
- Many commands have aliases (e.g., `b` for `bookmark`, `c` for `commit`)
- Commands like `git`, `operation`, and others have subcommands for specific functionality

## Core Commands

### Repository Management
- **init** — Initialize a repository
- **status** — Show the working copy status
- **log** — Show commit history
- **show** — Show a revision

### Change Operations
- **new** — Create a new change
- **edit** — Edit a change in the working copy
- **commit** — Update the description and create a new change on top [alias: c]
- **describe** — Update the description of a change
- **abandon** — Abandon a revision
- **duplicate** — Create a copy of revisions

### Content and Diff Operations
- **diff** — Show changes in a revision
- **diffedit** — Edit changes in a revision with a diff editor
- **interdiff** — Show the differences between two diffs
- **resolve** — Resolve a conflicted file
- **restore** — Restore paths from another revision

### History Manipulation
- **move** — Move changes from one revision into another
- **rebase** — Rebase revisions onto a new parent
- **split** — Split a revision into two
- **squash** — Squash a revision into its parent
- **absorb** — Move changes from a revision into the stack of mutable revisions
- **parallelize** — Parallelize revisions by making them siblings

### Navigation
- **next** — Move to the next revision in history
- **prev** — Move to the previous revision in history

### Bookmarks and Tags
- **bookmark** — Manage bookmarks [alias: b]
- **tag** — Manage tags

## Git Integration Commands

- **git** — Git integration commands
  - **git init** — Initialize a Git repository
  - **git fetch** — Fetch from a Git remote
  - **git push** — Push changes to a Git remote
  - **git root** — Show the Git root directory
  - **git remote** — Manage Git remotes
    - **git remote add** — Add a Git remote
    - **git remote list** — List Git remotes
    - **git remote remove** — Remove a Git remote
    - **git remote rename** — Rename a Git remote
    - **git remote set-url** — Set Git remote URL

## Operations Management

- **operation** — View and manage operations
  - **operation abandon** — Abandon operation history
  - **operation diff** — Show changes in an operation
  - **operation log** — Show operation history
  - **operation restore** — Restore to a previous operation
  - **operation show** — Show an operation
  - **operation undo** — Undo an operation
- **undo** — Undo an operation (shorthand for `operation undo`)

## Advanced Features

### Evolution and History
- **evolog** — Show the evolution log of a change

### File Operations
- **file** — File operations
- **fix** — Update files with formatting fixes or other changes

### Signing
- **sign** — Sign revisions with your configured signing backend
- **unsign** — Remove signatures from revisions

### Configuration
- **config** — Manage config options

### Workspace Management
- **workspace** — Manage workspaces

## Utility Commands

- **help** — Print help information
- **util** — Utility commands
  - **util completion** — Generate shell completions
  - **util config-schema** — Print the JSON schema for the jj TOML config format

## Common Aliases

- `b` → `bookmark`
- `c` → `commit`

## Usage Tips

1. **Getting Help**: Use `jj help` for general help or `jj help <command>` for specific command help
2. **Shell Completion**: Generate completions with `jj util completion <shell>` (supports bash, elvish, fish, nushell, powershell, zsh)
3. **Configuration**: Use `jj config` commands to manage settings
4. **Git Compatibility**: Use `jj git` subcommands for Git repository integration

## Reference Source

This information is based on Jujutsu v0.32.0 documentation from https://jj-vcs.github.io/jj/v0.32.0/cli-reference/