# Contributing

Thanks for your interest in improving this repository.

## Getting set up

```bash
git clone https://github.com/aidless/auto-research-driver.git
cd auto-research-driver
pip install -r requirements.txt   # if present
```

## Verifying your change

```bash
python3 -m pip install pytest pyyaml
make check
```

`make check` is what `checks.yml` and `pr-checks.yml` run. It does not call sister repositories.

## Pull requests

- One logical change per pull request.
- Explain what breaks or is missing without the change.
- State how you verified it, and paste the command output.
- Keep unrelated reformatting out of the diff.

## Security

Do not open a public issue for a security problem. Use the private channel described
in [SECURITY.md](SECURITY.md).

## Code of conduct

Participation is governed by [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
