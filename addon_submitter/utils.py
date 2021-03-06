from __future__ import unicode_literals
import logging
import os
import shutil
import subprocess
import sys
from collections import namedtuple
from io import open
from xml.etree import ElementTree as etree
import requests

__all__ = [
    'create_zip',
    'get_addon_info',
    'create_addon_branch',
    'create_pull_request'
]

AddonInfo = namedtuple('AddonInfo', ['name', 'version', 'description', 'news'])

REPO_URL_MASK = 'https://{}@github.com/{}.git'
PR_ENDPOINT = 'https://api.github.com/repos/xbmc/{}/pulls'

devnull = open(os.devnull, 'w')

logging.basicConfig(level=10, format='%(name)s - %(levelname)s: %(message)s')
logger = logging.getLogger('addon-submitter')


class AddonSubmissionError(Exception):
    pass


def create_zip(zip_name, addon_id, subdirectory):
    """Create a .zip for an addon
    
    :param zip_name: .zip file name
    :type zip_name: str
    :param addon_id: addon_id ID
    :type addon_id: str
    :param subdirectory:
    :type addon_id: bool
    """
    logger.info('Creating ZIP file...')
    if subdirectory:
        shell('git', 'archive', '-o', '{}.zip'.format(zip_name), 'HEAD', '--', addon_id)
    else:
        shell('git', 'archive', '-o', '{}.zip'.format(zip_name), '--prefix', '{}/'.format(addon_id), 'HEAD')
    logger.info('ZIP created successfully.')


def get_addon_info(xml_path):
    """Extract addon info from addon.xml

    :param xml_path: path to addon.xml
    """
    tree = etree.parse(xml_path)
    addon_tag = tree.getroot()
    descr_tag = addon_tag.find('.//description[@lang="en_GB"]')
    if descr_tag is None:
        descr_tag = addon_tag.find('.//description[@lang="en"]')
        if descr_tag is None:
            raise AddonSubmissionError(
                'Unable to find an English description in addon.xml!'
            )
    news_tag = addon_tag.find('.//news')
    if news_tag is not None:
        news = news_tag.text
    else:
        news = ''
    return AddonInfo(
        addon_tag.attrib.get('name'),
        addon_tag.attrib.get('version'),
        descr_tag.text,
        news
    )


def shell(*args, check=True):
    """Execute shell command"""
    if sys.version_info >= (3, 5):
        subprocess.run(args, check=check, stdout=devnull, stderr=devnull)
    else:
        if check:
            subprocess.check_call(args, stdout=devnull, stderr=devnull)
        else:
            subprocess.call(args, stdout=devnull, stderr=devnull)


def create_addon_branch(work_dir, repo, branch, addon_id, version, subdirectory):
    """ Create and addon branch in your fork of the respective addon repo

    :param work_dir: working directory
    :param repo: addon repo name, e.g. 'repo-scripts' or 'repo-plugins'
    :param branch: repo branch that corresponds to Kodi version codename,
        e.g. 'leia'
    :param addon_id: addon ID, e.g. 'plugin.video.example'
    :param version: addon version
    :param subdirectory: 
    """
    logger.info('Creatind addon branch...')
    gh_username = os.environ['GH_USERNAME']
    gh_token = os.environ['GH_TOKEN']
    email = os.environ['EMAIL']
    repo_fork = REPO_URL_MASK.format(
        gh_token,
        '{}/{}'.format(gh_username, repo)
    )
    repo_dir = os.path.join(work_dir, repo)
    if os.path.exists(repo_dir):
        shutil.rmtree(repo_dir)
    shell('git', 'clone', '--branch', branch, '--origin', 'upstream', '--single-branch', 'git://github.com/xbmc/{}.git'.format(repo))
    os.chdir(repo)
    shell('git', 'config', 'user.name', '{}'.format(gh_username))
    shell('git', 'config', 'user.email', email)
    shell('git', 'checkout', '-b', addon_id, 'upstream/{}'.format(branch))
    shutil.rmtree(os.path.join(work_dir, repo, addon_id), ignore_errors=True)
    os.chdir('..')
    if subdirectory:
        shell('sh', '-c', 'git archive --format tgz HEAD -- {} | tar zxf - -C {}'.format(addon_id, repo_dir))
    else:
        shell('sh', '-c', 'git archive --format tgz HEAD --prefix {}/ | tar zxf - -C {}'.format(addon_id, repo_dir))
    os.chdir(repo)
    shell('git', 'add', '--', addon_id)
    shell(
        'git', 'commit',
        '-m', '[{}] {}'.format(addon_id, version)
    )
    shell('git', 'push', '-f', '-q', repo_fork, addon_id)
    logger.info('Addon branch created successfully.')


def create_pull_request(repo, branch, addon_id, addon_info):
    """Create a pull request in the official repo on GitHub

    :param repo: addon repo name, e.g. 'repo-scripts' or 'repo-plugins'
    :param branch: repo branch that corresponds to Kodi version codename,
        e.g. 'leia'
    :param addon_id: addon ID, e.g. 'plugin.video.example'
    :param addon_info: AddonInfo object
    """
    gh_username = os.environ['GH_USERNAME']
    gh_token = os.environ['GH_TOKEN']
    logger.info('Checking pull request...')
    resp = requests.get(
        PR_ENDPOINT.format(repo),
        params={
            'head': '{}:{}'.format(gh_username, addon_id),
            'base': branch,
        },
        headers={'Accept': 'application/vnd.github.v3+json'},
        auth=(gh_username, gh_token)
    )
    logger.debug(resp.json())
    if resp.status_code == 200 and not resp.json():
        logger.info('Submitting pull request...')
        payload = {
            'title': '[{}] {}'.format(addon_id, addon_info.version),
            'head': '{}:{}'.format(gh_username, addon_id),
            'base': branch,
            'body': '{}\n\n{}'.format(addon_info.description, addon_info.news),
            'maintainer_can_modify': True,
        }
        resp = requests.post(
            PR_ENDPOINT.format(repo),
            json=payload,
            headers={'Accept': 'application/vnd.github.v3+json'},
            auth=(gh_username, gh_token)
        )
        if resp.status_code != 201:
            raise AddonSubmissionError(
                'GitHub API error: {}\n{}'.format(resp.status_code, resp.text)
            )
        logger.debug(resp.json())
        logger.info('Pull request submitted successfully:')
    elif resp.status_code == 200 and resp.json():
        logger.info(
            'Pull request in {} for {}:{} already exists.'.format(
                branch, gh_username, addon_id)
        )
    else:
        raise AddonSubmissionError(
            'Unexpected GitHub error: {}'.format(resp.status_code)
        )
