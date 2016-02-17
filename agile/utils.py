import os
import asyncio
import logging
import configparser
from datetime import date
from importlib import import_module
from collections import Mapping

import pulsar
from pulsar import ImproperlyConfigured

from jinja2 import Template


class AgileError(Exception):
    pass


class AgileExit(AgileError):
    pass


class ShellError(AgileError):

    def __init__(self, msg, code):
        super().__init__(msg)
        self.code = code


class AgileApps(dict):

    async def __call__(self, manager, command):
        bits = command.split(':')
        key = bits[0]
        entry = None
        if len(bits) == 2:
            entry = bits[1]
        elif len(bits) > 2:
            raise ImproperlyConfigured('bad command %s' % command)

        App = self.get(key)
        if not App:
            raise ImproperlyConfigured('No such command "%s"' % key)

        config = manager.config.get(key)
        if not config:
            raise ImproperlyConfigured('No entry "%s" in %s' %
                                       (key, manager.cfg.config_file))

        options = config.pop('options', {})
        app = App(manager)

        if entry is not None:
            cfg = config.get(entry)
            if not cfg:
                raise ImproperlyConfigured('No entry "%s" in %s' %
                                           (command, manager.cfg.config_file))
            cfg = as_dict(cfg, '%s entry not valid' % entry)
            await app(entry, cfg, options)
        else:
            for entry, cfg in config.items():
                cfg = as_dict(cfg, '%s entry not valid' % entry)
                await app(entry, cfg, options)


agile_apps = AgileApps()


class AgileMeta(type):
    """A metaclass which collects all setting classes and put them
    in the global ``KNOWN_SETTINGS`` list.
    """
    def __new__(cls, name, bases, attrs):
        abstract = attrs.pop('abstract', False)
        attrs['command'] = attrs.pop('command', name.lower())
        new_class = super().__new__(cls, name, bases, attrs)
        new_class.logger = logging.getLogger('agile.%s' % new_class.command)
        if not abstract:
            agile_apps[new_class.command] = new_class
        return new_class


class AgileApp(metaclass=AgileMeta):
    """Base class for agile applications
    """
    abstract = True
    description = 'Agile application'

    def __init__(self, app):
        self.app = app

    def __call__(self, entry, cfg, options):
        pass

    def __getattr__(self, name):
        return getattr(self.app, name)


class AgileSetting(pulsar.Setting):
    virtual = True
    app = 'agile'
    section = "Git Agile"


async def execute(command):
    """Execute a shell command
    :param args: a given number of command parameters
    :return: the output text
    """
    proc = await asyncio.create_subprocess_shell(
        command, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT)
    await proc.wait()
    msg = await proc.stdout.read()
    msg = msg.decode('utf-8').strip()
    if proc.returncode:
        raise ShellError(msg, proc.returncode)
    return msg


def passthrough(manager, version):
    """A simple pass through function

    :param manager: the release app
    :param version: release version
    :return: nothing
    """
    pass


def skipfile(name):
    return name.startswith('.') or name.startswith('__')


def render(text, context):
    template = Template(text)
    return template.render(**context)


def semantic_version(tag):
    """Get a valid semantic version for tag
    """
    try:
        version = list(map(int, tag.split('.')))
        assert len(version) == 3
        return tuple(version)
    except Exception:
        raise ImproperlyConfigured('Could not parse tag, please use '
                                   'MAJOR.MINOR.PATCH')


def get_auth():
    """Return a tuple for authenticating a user

    If not successful raise ``ImproperlyConfigured``.
    """
    home = os.path.expanduser("~")
    config = os.path.join(home, '.gitconfig')
    if not os.path.isfile(config):
        raise ImproperlyConfigured('.gitconfig file not available in %s'
                                   % home)

    parser = configparser.ConfigParser()
    parser.read(config)
    if 'user' in parser:
        user = parser['user']
        if 'username' not in user:
            raise ImproperlyConfigured('Specify username in %s user '
                                       'section' % config)
        if 'token' not in user:
            raise ImproperlyConfigured('Specify token in %s user section'
                                       % config)
        return user['username'], user['token']
    else:
        raise ImproperlyConfigured('No user section in %s' % config)


def change_version(manager, version):
    version_file = manager.cfg.version_file
    if not version_file:
        mod = import_module(manager.cfg.app_module)
        version_file = mod.__file__
        bits = version_file.split('.')
        bits[-1] = 'py'
        version_file = '.'.join(bits)

    def _generate():
        with open(version_file, 'r') as file:
            text = file.read()

        for line in text.split('\n'):
            if line.startswith('VERSION = '):
                yield 'VERSION = %s' % str(version)
            else:
                yield line

    text = '\n'.join(_generate())
    with open(version_file, 'w') as file:
        file.write(text)


async def write_notes(manager, release):
    history = os.path.join(manager.releases_path, 'history')
    if not os.path.isdir(history):
        return False
    dt = date.today()
    dt = dt.strftime('%Y-%b-%d')
    vv = release['tag_name']
    hist = '.'.join(vv.split('.')[:-1])
    filename = os.path.join(history, '%s.md' % hist)
    body = ['# Ver. %s - %s' % (release['tag_name'], dt),
            '',
            release['body']]

    add_file = True

    if os.path.isfile(filename):
        # We need to add the file
        add_file = False
        with open(filename, 'r') as file:
            body.append('')
            body.append(file.read())

    with open(filename, 'w') as file:
        file.write('\n'.join(body))

    manager.logger.info('Added notes to changelog')

    if add_file:
        await manager.git.add(filename)


def as_list(entry, msg=None):
    if entry and not isinstance(entry, list):
        entry = [entry]
    if not entry:
        raise ImproperlyConfigured(msg or 'Not a valid entry')
    return entry


def as_dict(entry, msg=None):
    if not isinstance(entry, Mapping):
        raise ImproperlyConfigured(msg or 'Not a valid entry')
    return entry


def task_description(task):
    return task.get("description", "no description given")


class TaskCommand:

    def __init__(self, manager, task, running=None):
        self.manager = manager
        self.task = task
        self.running = set(running or ())
        if task not in self.all_tasks:
            raise ImproperlyConfigured('No such task "%s"' % task)
        self.info = as_dict(self.all_tasks[task],
                            'Task should be a dictionary')
        self.commands = as_list(self.info.get('command'),
                                'No command entry for "%s" task' % task)
        self.running.add(task)

    @property
    def all_tasks(self):
        return self.manager.config['tasks']

    async def __call__(self):
        self.manager.logger.info('Executing "%s" task - %s' %
                                 (self.task, task_description(self.info)))
        for command in self.commands:
            if command in self.running:
                raise ImproperlyConfigured('command already running')

            if command in self.all_tasks:
                # the command is another task
                command = TaskCommand(self.manager, command, self.running)
                await command()
            else:
                await agile_apps(self.manager, command)
