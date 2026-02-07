# Python Semantic Release Setup

## Issue

The Python Semantic Release GitHub Action fails with the following error:

```
remote: error: GH013: Repository rule violations found for refs/heads/main.
remote: - Changes must be made through a pull request.
```

## Root Cause

The repository has a GitHub Repository Rule that requires all changes to the main branch to be made through pull requests. The Python Semantic Release action needs to push version bump commits and tags directly to the main branch, which conflicts with this rule.

## Solution

There are two ways to fix this issue:

### Option 1: Configure Repository Rules to Allow Workflow Bypass (Recommended)

1. Go to repository Settings → Rules → Rulesets
2. Find the ruleset that applies to the main branch
3. Under "Bypass list", add the GitHub Actions workflow
4. Alternatively, create a bypass for the specific workflow or for all GitHub Actions

### Option 2: Use a Personal Access Token (PAT)

1. Create a fine-grained Personal Access Token with the following permissions:
   - Repository access: This repository only
   - Permissions:
     - Contents: Read and write
     - Metadata: Read-only
   - Check "Allow bypass of branch protection rules" if available

2. Add the PAT as a repository secret named `PAT_TOKEN`

3. The workflow is already configured to use `PAT_TOKEN` if available, falling back to `GITHUB_TOKEN`

## Workflow Changes Made

The workflow has been updated with the following improvements:

1. **Updated action versions**: Using `actions/checkout@v4` and `actions/setup-python@v5`
2. **Added permissions**: Explicit `id-token: write` and `contents: write` permissions
3. **Persist credentials**: Set to `false` to avoid credential conflicts
4. **Token configuration**: Supports both `PAT_TOKEN` (preferred) and `GITHUB_TOKEN` (fallback)
5. **Version pinning**: Using specific version `v9.18.0` of python-semantic-release action

## Testing

To test the fix:

1. Make a commit with a conventional commit message (e.g., `feat: add new feature`)
2. Push to a feature branch and create a PR
3. Merge the PR to main
4. The CI/CD workflow should run and successfully create a release

## References

- [Python Semantic Release Documentation](https://python-semantic-release.readthedocs.io/)
- [GitHub Repository Rules](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/about-rulesets)
- [GitHub Actions Permissions](https://docs.github.com/en/actions/security-guides/automatic-token-authentication)
