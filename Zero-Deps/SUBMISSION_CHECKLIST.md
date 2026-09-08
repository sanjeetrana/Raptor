# Final Submission Checklist — NoDepDB (Zero-Deps)

## Before you submit, confirm each of these:

### Code
- [ ] Repo is set to **public** (required for judging)
- [ ] Storage engine PR #1 status confirmed — merged into `main`, or
      explicitly documented as not-yet-merged in the README
- [ ] `client.py` behavior matches what's written in README/INSTALLATION.md
      (port 6380, no REPL/batch mode unless confirmed otherwise)
- [ ] No leftover personal files, secrets, or API keys committed
- [ ] `.gitignore` in place

### Documentation
- [ ] `README.md` — accurate, no fabricated features
- [ ] `STDLIB.md` — lists all standard-library substitutions from all members
- [ ] `INSTALLATION.md` — installation/usage instructions verified on a
      clean clone
- [ ] `TESTING.md` — testing instructions present and accurate
- [ ] `requirements.txt` — empty, confirming zero third-party dependencies

### Testing
- [ ] Fresh clone tested end-to-end following only the written docs
- [ ] Core commands (`SET`/`GET`/`DEL`) verified working
- [ ] Invalid input tested (doesn't crash server or client)

### Team / Branches
- [ ] Confirm which branch is the final one to submit (`main`, or does
      a feature branch need merging first?)
- [ ] `feature/docs-build-submission` reviewed by team lead before
      merging into `main`
- [ ] All teammates' work (storage, network, client) confirmed present
      on the branch being submitted

### Submission Form / Platform
- [ ] Correct GitHub repo link ready: `https://github.com/Maaz4484/Zero-Deps`
- [ ] Demo video recorded and link ready (if required)
- [ ] All team members listed on the submission form
- [ ] Submission form fully filled out
- [ ] Deadline confirmed, submitted with time to spare
