#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# === This file is part of Calamares - <https://github.com/calamares> ===
#
#   Copyright 2014, Aurélien Gâteau <agateau@kde.org>
#   Copyright 2017, Alf Gaida <agaida@siduction.org>
#   Copyright 2019, Adriaan de Groot <groot@kde.org>
#   Copyright 2019, Kevin Kofler <kevin.kofler@chello.at>
#
#   Calamares is free software: you can redistribute it and/or modify
#   it under the terms of the GNU General Public License as published by
#   the Free Software Foundation, either version 3 of the License, or
#   (at your option) any later version.
#
#   Calamares is distributed in the hope that it will be useful,
#   but WITHOUT ANY WARRANTY; without even the implied warranty of
#   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
#   GNU General Public License for more details.
#
#   You should have received a copy of the GNU General Public License
#   along with Calamares. If not, see <http://www.gnu.org/licenses/>.

import tempfile
import subprocess
import os

import libcalamares

import gettext
_ = gettext.translation("calamares-python",
                        localedir=libcalamares.utils.gettext_path(),
                        languages=libcalamares.utils.gettext_languages(),
                        fallback=True).gettext


def pretty_name():
    return _("Mounting partitions.")


def mount_partitions(root_mount_point, partitions):
    """
    Pass back mount point and filesystem for each partition.

    :param root_mount_point:
    :param partitions:
    """
    for partition in partitions:
        if "mountPoint" not in partition or not partition["mountPoint"]:
            continue
        # Create mount point with `+` rather than `os.path.join()` because
        # `partition["mountPoint"]` starts with a '/'.
        raw_mount_point = partition["mountPoint"]
        mount_point = root_mount_point + raw_mount_point

        # Ensure that the created directory has the correct SELinux context on
        # SELinux-enabled systems.
        os.makedirs(mount_point, exist_ok=True)
        subprocess.call(['chcon', '--reference=' + raw_mount_point,
                         mount_point])

        fstype = partition.get("fs", "").lower()

        if fstype == "fat16" or fstype == "fat32":
            fstype = "vfat"

        if "luksMapperName" in partition:
            libcalamares.utils.debug(
                "about to mount {!s}".format(partition["luksMapperName"]))
            libcalamares.utils.mount(
                "/dev/mapper/{!s}".format(partition["luksMapperName"]),
                mount_point,
                fstype,
                partition.get("options", ""),
                )

        else:
            libcalamares.utils.mount(partition["device"],
                                     mount_point,
                                     fstype,
                                     partition.get("options", ""),
                                     )

        # If the root partition is btrfs, we create a subvolume "@"
        # for the root mount point.
        # If a separate /home partition isn't defined, we also create
        # a subvolume "@home".
        # Finally we remount all of the above on the correct paths.
        if fstype == "btrfs" and partition["mountPoint"] == '/':
            has_home_mount_point = False
            for p in partitions:
                if "mountPoint" not in p or not p["mountPoint"]:
                    continue
                if p["mountPoint"] == "/home":
                    has_home_mount_point = True
                    break

            subprocess.check_call(['btrfs', 'subvolume', 'create',
                                   root_mount_point + '/@'])

            if not has_home_mount_point:
                subprocess.check_call(['btrfs', 'subvolume', 'create',
                                       root_mount_point + '/@home'])

            subprocess.check_call(["umount", "-v", root_mount_point])

            if "luksMapperName" in partition:
                libcalamares.utils.mount(
                    "/dev/mapper/{!s}".format(partition["luksMapperName"]),
                    mount_point,
                    fstype,
                    ",".join(
                        ["subvol=@", partition.get("options", "")]),
                    )
                if not has_home_mount_point:
                    libcalamares.utils.mount(
                        "/dev/mapper/{!s}".format(partition["luksMapperName"]),
                        root_mount_point + "/home",
                        fstype,
                        ",".join(
                            ["subvol=@home", partition.get("options", "")]),
                        )
            else:
                libcalamares.utils.mount(
                    partition["device"],
                    mount_point,
                    fstype,
                    ",".join(["subvol=@", partition.get("options", "")]),
                    )
                if not has_home_mount_point:
                    libcalamares.utils.mount(
                        partition["device"],
                        root_mount_point + "/home",
                        fstype,
                        ",".join(
                            ["subvol=@home", partition.get("options", "")]),
                        )


def run():
    """
    Define mountpoints.

    :return:
    """
    partitions = libcalamares.globalstorage.value("partitions")

    if not partitions:
        libcalamares.utils.warning("partitions is empty, {!s}".format(partitions))
        return (_("Configuration Error"),
                _("No partitions are defined for <pre>{!s}</pre> to use." ).format("mount"))

    root_mount_point = tempfile.mkdtemp(prefix="calamares-root-")

    # Guard against missing keys (generally a sign that the config file is bad)
    extra_mounts = libcalamares.job.configuration.get("extraMounts") or []
    extra_mounts_efi = libcalamares.job.configuration.get("extraMountsEfi") or []
    if not extra_mounts and not extra_mounts_efi:
        libcalamares.utils.warning("No extra mounts defined. Does mount.conf exist?")

    # Sort by mount points to ensure / is mounted before the rest
    partitions.sort(key=lambda x: x["mountPoint"])
    mount_partitions(root_mount_point, partitions)
    mount_partitions(root_mount_point, extra_mounts)

    all_extra_mounts = extra_mounts
    if libcalamares.globalstorage.value("firmwareType") == "efi":
        mount_partitions(root_mount_point, extra_mounts_efi)
        all_extra_mounts.extend(extra_mounts_efi)

    libcalamares.globalstorage.insert("rootMountPoint", root_mount_point)

    # Remember the extra mounts for the unpackfs module
    libcalamares.globalstorage.insert("extraMounts", all_extra_mounts)
