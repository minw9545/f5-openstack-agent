#!/usr/bin/python

from __future__ import print_function

import glob
import os
import re
import subprocess
import sys

from collections import deque, namedtuple

dep_match_re = re.compile('^\s*([\w\-]+)\s\(([=<>]+)\s([^\)]+)')


def usage():
    print("fetch_dependencies.py working_dir pkg.deb")


def runCommand(cmd):
    output = ""
    try:
        p = subprocess.Popen(cmd.split(),
                             stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE)
        (output) = p.communicate()[0]
    except OSError as e:
        print("Execution failed: [%s:%s] " % (cmd, os.listdir('/var/wdir')), e,
              file=sys.stderr)
    return (output, p.returncode)


def fetch_agent_dependencies(dist_dir, version, release, agent_pkg):
    # agent_pkg = "f5-openstack-agent_%s_1404_all.deb" % (version)
    ReqDetails = namedtuple('ReqDetails', 'name, oper, version')
    f5_sdk_version = None
    requires = deque()
    # Copy agent package to /tmp
    cpCmd = "cp %s /tmp" % agent_pkg
    print("Copying agent package to /tmp install directory")
    (output, status) = runCommand(cpCmd)
    if status != 0:
        print("Failed to copy f5-openstack-agent package")
    else:
        print("Success")

    # Get the openstack-agent requirement.
    requiresCmd = "dpkg -I %s" % agent_pkg
    agent_pkg_base = os.path.basename(agent_pkg)
    print("Getting dependencies for %s." % agent_pkg_base)
    (output, status) = runCommand(requiresCmd)

    if status != 0:
        print("Can't get package dependencies for %s (%s)" %
              (agent_pkg_base, output))
        return 1
    else:
        print("Success")

    for line in output.split('\n'):
        if 'Depends' not in line:
            continue
        for dep in output.split(','):
            match = dep_match_re.match(dep)
            if match:
                groups = list(match.groups())
                my_dep = ReqDetails(*groups)
                if 'f5-sdk' in my_dep.name and '=' in my_dep.oper and \
                        '!=' not in my_dep.oper:
                    f5_sdk_version = my_dep.version
                requires.append(my_dep)
        break

    # we know we will always need this...
    print("requires:", requires)
    if not f5_sdk_version:
        print("Can't find sdk dependency for %s" % (agent_pkg))
        return 1

    # Check if the required packages are present, then install the ones we are
    # aware of...
    # grab the sdk's:
    sdk_github_addr = \
        "https://github.com/F5Networks/f5-common-python" + \
        "/releases/download/v%s"
    github_sdk_url = (sdk_github_addr % re.sub("-\d+", "", f5_sdk_version))
    f5_sdk_pkg = "python-f5-sdk-rest_%s_1404_all.deb" % \
        (f5_sdk_version)
    f5_sdk_version_bld = "{}-1".format(f5_sdk_version) \
        if '-1' not in f5_sdk_version else f5_sdk_version
    curlCmd = \
        ("curl -L -o /tmp/%s %s/python-f5-sdk_%s_1404_all.deb" %
         (f5_sdk_pkg, github_sdk_url, f5_sdk_version_bld))

    print("Fetching f5-sdk package from github")
    (output, status) = runCommand(curlCmd)

    # Get the sdk dependency
    requiresCmd = "dpkg -I /tmp/%s" % (f5_sdk_pkg)
    print("Getting dependencies for %s." % (f5_sdk_pkg))
    (output, status) = runCommand(requiresCmd)

    if status != 0:
        print(('output', output))
        print("Failed to get requirements for %s." % (f5_sdk_pkg))
        return 1
    else:
        print("Success")

    sdk_requires = deque()
    for line in output.split('\n'):
        if 'Depends' not in line:
            continue
        for dep in output.split(','):
            match = dep_match_re.match(dep)
            if match:
                groups = list(match.groups())
                my_dep = ReqDetails(*groups)
                print("icontrol:", my_dep)
                if 'icontrol' in my_dep.name:
                    if re.search('^>?=', my_dep.oper):
                        f5_icontrol_rest_version = my_dep.version
                else:
                    sdk_requires.append(my_dep)
        break

    # we know we will always need this...
    print("sdk_requires:", sdk_requires)
    if not f5_icontrol_rest_version:
        print("Can't find icontrol rest dependency for %s" % (agent_pkg))
        return 1

    # Check if the required packages are present, then install the ones we are
    # aware of...
    # grab the sdk's:
    sdk_github_addr = \
        "https://github.com/F5Networks/f5-icontrol-rest-python" + \
        "/releases/download/v%s"
    version = re.sub('-\d+', '', f5_icontrol_rest_version)
    github_sdk_url = (sdk_github_addr % version)
    f5_icontrol_rest_pkg = "python-f5-icontrol-rest_%s-1_1404_all.deb" % version
    curlCmd = \
        ("curl -L -o /tmp/%s %s/%s" %
         (f5_icontrol_rest_pkg, github_sdk_url, f5_icontrol_rest_pkg))

    print("Fetching f5-icontrol-rest package from github")
    (output, status) = runCommand(curlCmd)

    # Get the icontrol rest dependency
    requiresCmd = "dpkg -I /tmp/%s" % (f5_icontrol_rest_pkg)
    print("Getting dependencies for %s." % (f5_icontrol_rest_pkg))
    (output, status) = runCommand(requiresCmd)
    if status != 0:
        print("Failed to get requirements for %s." % (f5_icontrol_rest_pkg))
        return 1
    else:
        print("Success")

    return check_other_dependencies(requires, dist_dir, agent_pkg)


def check_other_dependencies(requires, dist_dir, agent_pkg):
    # triage the packages already installed
    rpm_list_cmd = "dpkg -l"
    print("Collecting a list of already-install pkgs")
    (output, status) = runCommand(rpm_list_cmd)
    to_get = deque()
    ignore = ['f5-sdk']
    while requires:
        my_dep = requires.popleft()
        if my_dep.name not in output and my_dep.name not in ignore:
            to_get.append(my_dep)
    # install the repo-stored rpm's
    print("Grabbing the ones we have copies of")
    to_install = glob.glob(dist_dir + "/Docker/ubuntu/14.04/*.deb")
    for deb_file in to_install:
        for rpm_dep in to_get:
            if rpm_dep.name in deb_file:
                to_get.remove(rpm_dep)
        rpm_install_cmd = "dpkg -i %s" % deb_file
        runCommand(rpm_install_cmd)
    if to_get:
        print("WARNING: there are missing dependencies!")
        while to_get:
            dep = to_get.popleft()
            pkg = dep.name + "=" + dep.version
            if "f5-sdk" not in pkg:
                apt_get_cmd = "apt-get -y install " + pkg
                print(apt_get_cmd)
                (output, status) = runCommand(apt_get_cmd)
                if status:
                    print("ERROR: can not install missing dependencies %s "
                          "by apt-get" % pkg)
                    sys.exit(1)
                print("Install missing dependencies %s by apt-get" % pkg)
    else:
        print("""Succsess!
All dependencies search satisfied!  However, by-version check may still fail...
""")
    # change to be dynamic if we decide to be more rigorous at this stage...
    return 0


def install_agent_pkgs(repo):
    dpkgs = glob.glob(repo + "/*.deb")
    dpkgs.sort()
    order = ["icontrol", "sdk", "openstack"]
    for item in order:
        for dpkg in dpkgs:
            if item in dpkg:
                print("Installing: %s" % dpkg)
                installCmd = "dpkg -i %s" % dpkg
                (output, status) = runCommand(installCmd)
                if status != 0:
                    print("SDK install failed (%s)" % (str(status)))
                    sys.exit(1)
                else:
                    print("SDK Succeeded in install test")


def main(args):
    if len(args) != 3:
        usage()
        sys.exit(1)

    working_dir = os.path.normpath(args[1])
    pkg_fullname = args[2]
    try:
        os.chdir("/var/wdir")
    except OSError as e:
        print("Can't change to directory %s (%s)" %
              (working_dir, e), file=sys.stderr)

    dist_dir = os.path.join(working_dir, "f5-openstack-agent-dist")
    version_tool = os.path.join(dist_dir, "scripts/get-version-release.py")

    cmd = "%s --version --release" % (version_tool)
    (output, status) = runCommand(cmd)
    if status == 0:
        (version, release) = output.rstrip().split()

    # Get all files for the f5-sdk.
    fetch_agent_dependencies(dist_dir, version, release, pkg_fullname)

    # Instal from the tmp directory.
    install_agent_pkgs("/tmp")


if __name__ == '__main__':
    main(sys.argv)
