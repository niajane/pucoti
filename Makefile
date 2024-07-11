.PHONY: all run mkdist zip linux check_git_status poetry_patch poetry_minor poetry_major commit_version_bump publish patch minor major clean distclean

END=\033[0m
GREEN=\033[34m

all: linux zip

run:
	@poetry run python pucoti.py

mkdist:
	@mkdir -p dist

zip: mkdist
	@echo -e "$(GREEN)Updating zip...$(END)"
	@git ls-files | zip --filesync -r --names-stdin dist/pucoti.zip

linux: mkdist
	@echo -e "$(GREEN)Building for linux...$(END)"
	poetry run pyinstaller --noconsole --add-data assets/:assets --onefile pucoti.py

# windows: mkdist
# 	@echo -e "$(GREEN)Building for windows...$(END)"
# 	WINEDEBUG=-all wine pyinstaller.exe --noconsole --add-data src\\assets\;src\\assets --onefile pucoti.py

check_git_status:
	@if [ -n "$$(git status --porcelain)" ]; then \
		echo "Git working directory is not clean. Please commit or stash your changes."; \
		exit 1; \
	fi

poetry_patch:
	poetry version patch

poetry_minor:
	poetry version minor

poetry_major:
	poetry version major

commit_version_bump:
	@echo "Bumped version to $$(poetry version -s)"
	git add pyproject.toml
	git commit -m "chore: bump version to $$(poetry version -s)"
	git tag -a "v$$(poetry version -s)" -m "v$$(poetry version -s)"

check_git_status:
	@if [ -n "$$(git status --porcelain)" ]; then \
		echo "Git working directory is not clean. Please commit or stash your changes."; \
		read -p "Continue anyway? [y/N] " CONTINUE; \
		if [ "$$CONTINUE" != "y" ]; then \
			exit 1; \
		fi; \
	fi

publish:
	poetry publish --build

patch: check_git_status poetry_patch commit_version_bump zip linux publish
minor: check_git_status poetry_minor commit_version_bump zip linux publish
major: check_git_status poetry_major commit_version_bump zip linux publish


clean:
	rm -r build
	rm -r **/__pycache__ __pycache__

distclean: clean
	rm -r dist
