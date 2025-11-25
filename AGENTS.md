# Pull request naming
Create name using angular commit message format.
`feat:` and `fix:` are using in CHANGELOG.md. It's a release notes for developers. Name your PRs in a way that it's easy to understand what was changed. Forbidden to use `feat:` and `fix:` prefixes for chore tasks that don't add new features or fix bugs.

## Coding standards
- Use snake_case for variables, functions and config.
- In http server always use 200 status code for success responses and "answer" key with the response message.

## Rules on new features:
- Add documentation for new features to README.md
- Add new config variables to config.example.yml

Shared drive structure: Level 1: clients folders. Folder names as client name. Level 2+: client's files
