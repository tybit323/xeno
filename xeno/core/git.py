# System imports
from sys import exit
import os
from os.path import expanduser, exists, isfile, join, dirname, basename, \
    normpath, realpath, relpath
import subprocess
from subprocess import check_call, check_output
import uuid
from shutil import rmtree

# Setuptools imports
from pkg_resources import resource_string

# xeno imports
from xeno.core.output import print_error
from xeno.core.paths import get_working_directory
from xeno.core.configuration import get_configuration


def initialize_remote_repository(path):
    """This method initializes a remote repository which xeno can clone locally
    to do its editing.

    Args:
        path: The path of the file or directory that the repository should
            monitor and modify

    Returns:
        A string representing the repository path.
    """
    # Expand out the specified path
    path = realpath(normpath(expanduser(path)))

    # Validate it
    if not exists(path):
        print_error('Requested path does not exist: {0}'.format(path))
        exit(1)

    # Check what we're dealing with
    is_file = isfile(path)

    # Grab the xeno working directory.  Make sure it is real and normalized so
    # that we can check if the repository is a subdirectory of the work tree.
    xeno_working_directory = realpath(normpath(get_working_directory()))

    # Create a unique repository path.  We do not need to create the
    # repository - Git will do it for us.
    repo_path = join(xeno_working_directory, 'remote-' + uuid.uuid4().hex)

    # Figure out our working tree.  If we are editing a directory, it will be
    # the directory.  If we are editing a file, it will be the parent directory
    # and we will only include the file.
    work_path = dirname(path) if is_file else path

    # Do the initialization (--quiet has to come after init here)
    with open(os.devnull, 'w') as null_output:
        try:
            check_call(['git',
                        '--work-tree',
                        work_path,
                        '--git-dir',
                        repo_path,
                        'init',
                        '--quiet'],
                       stdout=null_output,
                       stderr=null_output)
        except:
            print_error('Unable to initialize remote repository')
            exit(1)

    # Set up excludes
    with open(join(repo_path, 'info', 'exclude'), 'a') as exclude_file:
        # If this is a single file, exclude everything but the file
        if is_file:
            exclude_file.write('*\n')
            exclude_file.write('!{0}\n'.format(basename(path)))

        # If this is not a file, there are a few things to do
        if not is_file:
            # First, if the work tree is at a higher path than the repository,
            # add the repository as an exclude path
            relative_path = relpath(repo_path, work_path)
            if not relative_path.startswith('..'):
                exclude_file.write('{0}\n'.format(relative_path))

            # All the major SCM dirs to the exclude
            for scm_dir in ['.git', '.svn', '.hg']:
                exclude_file.write('{0}\n'.format(scm_dir))

    # Add all files and do the initial commit.  We have to use this wildcard
    # expression for the pathspec due to how git behaves when the work tree is
    # above the repo directory.  In any case, I think git will always ignore
    # the repo directory.
    if not commit(repo_path,
                  commit_modified=False,
                  commit_created=True,
                  commit_deleted=False):
        print_error('Unable to add initial commit to remote repository')
        rmtree(repo_path)
        exit(1)

    # Create an incoming branch
    with open(os.devnull, 'w') as null_output:
        try:
            check_call(['git',
                        'branch',
                        'incoming'],
                       cwd=repo_path)
        except:
            print_error('Unable to add incoming branch to remote repository')
            rmtree(repo_path)
            exit(1)

    # Install hooks.  Note that it is required to use forward-slashes in the
    # pkg_resources API, and they will automatically be translated
    # appropriately on any platform
    post_receive_script = resource_string('xeno', 'hooks/post-receive')
    hook_file_path = join(repo_path, 'hooks', 'post-receive')
    with open(hook_file_path, 'w') as hook_file:
        hook_file.write(post_receive_script)
    os.chmod(hook_file_path, 0o700)

    return repo_path


def clone(clone_url, local_destination):
    """Clones a remote URL to a local path, pulling down all branches and
    setting them up to track from the remote.

    This method will print an error and exit on failure.

    Args:
        clone_url: The repository URL
        local_destination: The local path to clone into.  It must not exist.
    """
    # Do the clone
    _check_call(['git',
                 'clone',
                 '--quiet',
                 clone_url,
                 local_destination],
                'Unable to clone remote repository')


def commit(repo_path, commit_modified, commit_created, commit_deleted):
    """Checks if there are any changes to the repository and commits them.

    Args:
        repo_path: The path to the repository
        commit_modified: Whether or not to commit modified files
        commit_created: Commit new (untracked) files
        commit_deleted: Commit deletions

    Returns:
        True if a new commit was created, False if not.
    """
    # First check what files have been modified/created/deleted
    try:
        # All files which have been modified or deleted
        modified_deleted = check_output(['git',
                                         'ls-files',
                                         '--modified',
                                         '--exclude-standard'],
                                        cwd=repo_path).split(os.linesep)

        # All files which have been deleted
        deleted = check_output(['git',
                                'ls-files',
                                '--deleted',
                                '--exclude-standard'],
                               cwd=repo_path).split(os.linesep)

        # All files which have been modified
        modified = list(set(modified_deleted) - set(deleted))

        # All files which have been created
        created = check_output(['git',
                                'ls-files',
                                '--other',
                                '--exclude-standard'],
                               cwd=repo_path).split(os.linesep)
    except:
        # Just ignore errors, but don't commit
        return False

    # Now stage all requested changes
    changes_added = False

    # Muffle all output
    null_output = open(os.devnull, 'w')

    # Commit modified files
    if commit_modified and modified:
        changes_added = True
        for path in modified:
            try:
                check_call(['git',
                            'add',
                            path],
                           cwd=repo_path,
                           stdout=null_output,
                           stderr=null_output)
            except:
                # Ignore errors here for now
                pass

    # Commit deleted files
    if commit_deleted and deleted:
        changes_added = True
        for path in deleted:
            try:
                check_call(['git',
                            'rm',
                            path],
                           cwd=repo_path,
                           stdout=null_output,
                           stderr=null_output)
            except:
                # Ignore errors here for now
                pass

    # Commit new files
    if commit_created and created:
        changes_added = True
        for path in created:
            try:
                check_call(['git',
                            'add',
                            path],
                           cwd=repo_path,
                           stdout=null_output,
                           stderr=null_output)
            except:
                # Ignore errors here for now
                pass

    # If we added anything, do the commit
    commited = False
    if changes_added:
        try:
            check_call(['git',
                        'commit',
                        '--quiet',
                        '-a',
                        '--author',
                        '"xeno <xeno@xeno>"',
                        '-m',
                        '"xeno-commit"'],
                       cwd=repo_path,
                       stdout=null_output,
                       stderr=null_output)
            commited = True
        except:
            # Ignore errors here for now
            pass

    # Close null output
    null_output.close()

    return commited


def have_unpushed_commits(repo_path):
    """Returns True if there are unpushed commits with respect to the remote.

    Args:
        repo_path: The path to the repository

    Returns:
        True if there are unpushed commits, False otherwise.
    """
    try:
        return check_output(['git',
                             'diff',
                             '--shortstat',
                             'origin/master'],
                            cwd=repo_path) != ''
    except:
        # Ignore errors
        return False


def sync_local_with_remote(repo_path,
                           poll_for_remote_changes,
                           remote_is_file):
    """Commits all local changes, pushes them to the remote branch, and pulls
    down any new changes.

    In all cases where there are conflicts, the local always take precedence
    over the remote.

    Args:
        repo_path: The path of the repository to sync
        poll_for_remote_changes: If False, this method will only initiate a
            push/pull when there are local changes
        remote_is_file: Whether or not the remote is a single file

    Returns:
        True on success, False on error.
    """
    # Commit our local changes, and if there are any commits, we need to push
    # them
    do_push = commit(repo_path,
                     commit_modified=True,
                     commit_created=(not remote_is_file),
                     commit_deleted=(not remote_is_file))

    # If we didn't commit anything, check if we have any pending commits that
    # need to be pushed
    do_push = do_push or have_unpushed_commits(repo_path)

    # If we still don't have any reason to push, check if the user wants to
    # explicitly poll for changes from the remote.  If yes, then we need to do
    # a push (even an empty one) to get the remote to look for changes on its
    # end.
    do_push = do_push or poll_for_remote_changes

    # At this point, if we're not doing a push, we can bail
    if not do_push:
        return True

    # Muffle all output
    null_output = open(os.devnull, 'w')

    # Push the local branch and pull from the remote
    try:
        check_call(['git',
                    'push',
                    '--quiet',
                    '--receive-pack',
                    'xeno-receive-pack',
                    'origin',
                    'master:incoming'],
                   cwd=repo_path,
                   stdout=null_output,
                   stderr=null_output)

        check_call(['git',
                    'pull',
                    '--quiet',
                    '--commit',
                    '--no-edit',
                    '--strategy',
                    'recursive',
                    '-X',
                    'ours'],
                   cwd=repo_path,
                   stdout=null_output,
                   stderr=null_output)
    except:
        null_output.close()
        return False

    # Cleanup
    null_output.close()

    # All done
    return True


def self_destruct_remote(repo_path):
    """This method creates a self-destruct commit message and pushes it to the
    remote end.

    On the remote end, only the bare repository is deleted - the working tree
    is left untouched.

    Args:
        repo_path: The path to the repository
    """
    try:
        # Create the destructive commit
        subprocess.call(['git',
                         'commit',
                         '--quiet',
                         '--author',
                         '"xeno <xeno@xeno>"',
                         '-m',
                         '"xeno-destruct"',
                         '--allow-empty'],
                        cwd=repo_path)

        # Push it to the remote, ignoring all output because the remote will
        # spit back a fatal error
        with open(os.devnull, 'w') as devnull_output:
            subprocess.check_call(['git',
                                   'push',
                                   '--quiet',
                                   'origin',
                                   'master:incoming'],
                                  cwd=repo_path,
                                  stdout=devnull_output,
                                  stderr=devnull_output)
    except:
        # Oh well, we did our best..., just let it pass but print a message
        print_error('Unable to self-destruct remote repository')


def add_metadata_to_repo(repo_path, key, value):
    """Sets the specified key to the specified value on the specified
    repository, adding it in the xeno section.

    This method will print an error and exit on failure.

    Args:
        repo_path: The path to the repository
        key: The key to set, must be camel case
        value: The value to set the key to
    """
    # Set the value
    _check_call(['git',
                 'config',
                 'xeno.{0}'.format(key),
                 value],
                'Unable to set repository metadata',
                cwd=repo_path)


def get_metadata_from_repo(repo_path, key):
    """Retrieve the metadata associated with the specified key in the specified
    repository under the xeno section.

    This method will print an error and exit on failure.  If the specified key
    doesn't exist, this method returns an empty string.

    Args:
        repo_path: The path to the repository
        key: The key to read, must be camel case

    Returns:
        The value associated with the key, if it exists, otherwise an empty
        string.  This method exits on failure.
    """
    try:
        output = subprocess.check_output(['git',
                                          'config',
                                          'xeno.{0}'.format(key)],
                                         cwd=repo_path)
    except:
        print_error('Unable to read repository metadata')
        exit(1)

    return output.strip()


def cloneable_remote_path(username, hostname, port, repo_path):
    """Constructs a cloneable Git URL capable of cloning the remote path.

    Args:
        username: The username to clone with or None
        hostname: The hostname to clone from
        port: The port to clone from or None
        repo_path: The path of the repository on the remote

    Returns:
        A string representing the cloneable path.
    """
    return 'ssh://{0}{1}{2}/{3}'.format(
        '{0}@'.format(username) if username else '',
        hostname,
        ':{0}'.format(port) if port else '',
        repo_path
    )
