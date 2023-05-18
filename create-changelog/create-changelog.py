#
# Copyright (c) 2023 Alan de Freitas (alandefreitas@gmail.com)
#
# Distributed under the Boost Software License, Version 1.0.
# (See accompanying file LICENSE_1_0.txt or copy at http://www.boost.org/LICENSE_1_0.txt)
#
import argparse
import os
import subprocess
import re


class Commit:
    def __init__(self):
        self.type = None
        self.scope = None
        self.description = None
        self.body = None
        self.breaking = False


if __name__ == "__main__":
    # Args
    parser = argparse.ArgumentParser(description='Installs the dependencies needed to test a Boost library.')
    parser.add_argument('--dir', help="directory to scan", default=os.getcwd())
    parser.add_argument('--version-pattern', help="regex pattern indicating a version commit",
                        default='(Bump|Set)\s+version')
    parser.add_argument('--tag-pattern', help="regex indicating a tagged commit",
                        default='v.*\..*\..*')
    parser.add_argument('-o', '--output', help="output file", default='CHANGELOG.md')
    parser.add_argument('--limit', type=int, help="max number of commits in the log", default=0)
    args = parser.parse_args()

    # Parameters
    project_path = args.dir
    version_pattern = re.compile(args.version_pattern, flags=re.IGNORECASE)
    tag_pattern = re.compile(args.tag_pattern, flags=re.IGNORECASE)
    output_path = args.output

    # Get commit log
    result = subprocess.run(['git', '--no-pager', 'log'], stdout=subprocess.PIPE, cwd=project_path)
    commit_log_output = result.stdout.decode('utf-8').splitlines()

    # Get tagged commits
    tagged_commit_ids = set()
    commit_tags = {}
    tags_result = subprocess.run(['git', 'tag', '-l'], stdout=subprocess.PIPE, cwd=project_path)
    tags_output = tags_result.stdout.decode('utf-8').splitlines()
    for tag in tags_output:
        matches = re.findall(tag_pattern, tag)
        if matches:
            commit_result = subprocess.run(['git', 'rev-list', '-n', '1', tag], stdout=subprocess.PIPE,
                                           cwd=project_path)
            commit_id = commit_result.stdout.decode('utf-8').strip()
            tagged_commit_ids.add(commit_id)
            commit_tags[commit_id] = tag
    ls_remote_result = subprocess.run(['git', 'ls-remote', '--tags'], stdout=subprocess.PIPE, cwd=project_path)
    ls_remote_output = ls_remote_result.stdout.decode('utf-8').splitlines()
    for line in ls_remote_output:
        parts = line.split()
        if len(parts) == 2 and parts[1].startswith("refs/tags/"):
            commit_id = parts[0]
            tag = parts[1].split('/')[-1]
            matches = re.findall(tag_pattern, tag)
            if matches:
                tagged_commit_ids.add(commit_id)
                commit_tags[commit_id] = tag
    print(f'{len(tagged_commit_ids)} tagged commits')

    state = 'init'
    commit_msgs = []
    delimiter_commit_id = ''
    msg = ''
    for line in commit_log_output:
        if state == 'init' and line.startswith('commit ') and ' ' not in line[7:]:
            # expect author now
            if msg != '':
                commit_msgs.append(msg)
            msg = ''
            delimiter_commit_id = line[7:]
            if commit_msgs and delimiter_commit_id in tagged_commit_ids:
                break
            state = 'author'
            continue
        if state == 'author' and line.startswith('Author:'):
            # expect date now
            state = 'date'
            continue
        if state == 'date' and line.startswith('Date:'):
            # expect empty line
            state = 'empty after date'
            continue
        if state == 'empty after date' and line == '':
            # expect commit message now
            state = 'message'
            continue
        if state == 'message' and line.startswith('    '):
            # expect empty line and other commit or empty line and comments
            msg += line[4:]
            if commit_msgs:
                # don't match if commit_msgs is still empty
                matches = re.findall(version_pattern, msg)
                if matches:
                    break
            state = 'init'
            continue
        if state == 'init' and line == '':
            continue
        if state == 'init' and line.startswith('    '):
            msg += "\n\n" + line[4:]
            continue
    if msg != '':
        commit_msgs.append(msg)
    print(f'{len(commit_msgs)} commit messages')

    if args.limit:
        commit_msgs = commit_msgs[:args.limit]
        print(f'Limited to {args.limit}')


    def normalize(s):
        category_mapping = {
            'doc': 'docs',
            'documentation': 'docs',
            'fixes': 'fix',
            'bugfix': 'fix',
            'work': 'chore',
            'chores': 'chore',
            'maintenance': 'chore',
            'feature': 'feat',
            'cleanup': 'refactor',
            'performance': 'perf',
            'testing': 'test',
            'tests': 'test',
            'version': 'release',
            'integration': 'ci',
            'break': 'breaking',
            'undo': 'revert',
        }
        return category_mapping.get(s.lower(), s)


    # Parse commit messages
    commits = []
    conventional_regex = r'([ \d\w_-]+)(\(([ \d\w_-]+)\))?(!?): ([^\n]*)\n?(.*)'
    commit = Commit()
    for c in commit_msgs:
        m = re.match(conventional_regex, c)
        if m:
            # conventional commit
            commit.type = normalize(m[1])
            commit.scope = m[3]
            commit.description = m[5]
            parts = c.split('\n', 1)
            commit.body = '' if len(parts) < 2 else parts[1].strip()
            commit.breaking = m[4] == '!' or commit.body.find('BREAKING CHANGE') != -1
            commits.append(commit)
            commit = Commit()
            continue

        # regular commit
        description = c
        body = ''
        description_end = description.find('\n')
        if description_end != -1:
            body = description[description_end:]
            description = description[:description_end]

        commit.type = 'other'
        commit.scope = None
        commit.description = description
        commit.body = body
        commit.breaking = c.find('BREAKING') != -1
        commits.append(commit)
        commit = Commit()

    # Create dictionary of changes by type and scope
    changes = {}
    for c in reversed(commits):
        if c.type not in changes:
            changes[c.type] = {}
        if c.scope not in changes[c.type]:
            changes[c.type][c.scope] = []
        changes[c.type][c.scope].append(c)
    print(f'{len(changes)} change categories:')

    # Sort commit type by priority
    change_type_priority = ['feat', 'fix', 'perf', 'refactor', 'docs', 'style', 'build', 'test', 'ci', 'chore',
                            'release']
    for type in changes.keys():
        if type not in change_type_priority:
            change_type_priority.append(type)
    if 'other' not in change_type_priority:
        change_type_priority.append('other')


    def humanize(s):
        m = {
            'docs': 'Documentation',
            'fix': 'Fixes',
            'style': 'Style',
            'chore': 'Chores',
            'build': 'Build',
            'feat': 'Features',
            'refactor': 'Refactor',
            'perf': 'Performance',
            'test': 'Tests',
            'release': 'Release',
            'ci': 'Continuous Integration',
            'improvement': 'Improvement',
            'breaking': 'Breaking',
            'revert': 'Revert',
            'other': 'Other'
        }
        if s in m:
            return m[s]
        return s


    # https://github.com/favoloso/conventional-changelog-emoji#available-emojis
    def icon_for(s):
        m = {
            'docs': '📖',
            'fix': '🐛',
            'style': '🎨',
            'chore': '🏗️',
            'build': '📦️',
            'feat': '🚀',
            'refactor': '♻️',
            'perf': '⚡️',
            'test': '🧪',
            'release': '🔖',
            'ci': '🚦',
            'improvement': '🛠️',
            'breaking': '🚨',
            'revert': '🔙',
            'other': '💬',
            None: '💬'
        }
        if s in m:
            return m[s]
        return s


    def good_icon():
        icon = [
            '✨',
            '💫',
            '🌟',
        ][good_icon.count % 3]
        good_icon.count += 1
        return icon


    good_icon.count = 0

    # Generate output
    output = ''
    footnotes_output = ''
    footnotes_count = 1
    for change_type in change_type_priority:
        if change_type in changes:
            scope_changes = changes[change_type]
            if len(changes) > 1 or (len(changes) > 0 and change_type[0] != 'other'):
                output += f'\n## {icon_for(change_type)} {humanize(change_type)}\n\n'
            for [scope, commits] in scope_changes.items():
                pad = ''
                scope_prefix = ''
                if scope is not None:
                    if len(commits) > 1:
                        output += f'- {scope}:\n'
                        pad = '    '
                    else:
                        scope_prefix = f'{scope}: '

                for c in commits:
                    if c.type == "feat":
                        feat_icon = good_icon() + " "
                    else:
                        feat_icon = ''
                    if c.breaking:
                        breaking_suffix = " (" + icon_for("breaking") + " BREAKING)"
                    else:
                        breaking_suffix = ''
                    if c.body:
                        comment_suffix = f"[^{footnotes_count}]"
                        footnote = c.body.replace("\n", "").strip()
                        footnotes_output += f'[^{footnotes_count}]: {footnote}\n'
                        footnotes_count += 1
                    else:
                        comment_suffix = ""
                    output += f'{pad}- {feat_icon}{scope_prefix}{c.description}{breaking_suffix}{comment_suffix}\n'

    if delimiter_commit_id in tagged_commit_ids and delimiter_commit_id in commit_tags:
        parent_tag = commit_tags[delimiter_commit_id]
        parent_id = delimiter_commit_id[:7]
        cmd = ['git', 'config', '--get', 'remote.origin.url']
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
        output += '\n\n'
        if result.returncode == 0:
            # Decode output and remove any trailing whitespace
            repo_url = result.stdout.strip()
            if repo_url.endswith('.git'):
                repo_url = repo_url[:-len('.git')]
            output += f'> Parent release: [{parent_tag}]({repo_url}/releases/tag/{parent_tag}) (commit [{parent_id}]({repo_url}/tree/{parent_tag}))\n'
        else:
            output += f'> Parent release: {parent_tag} (commit {parent_id})\n'

    if footnotes_output:
        output += '\n\n'
        output += footnotes_output

    print(f'CHANGELOG Contents:', output)

    output_path = os.path.abspath(output_path)
    print(f'Generating CHANGELOG: {output_path}')
    with open(output_path, "w") as f:
        f.write(output)
