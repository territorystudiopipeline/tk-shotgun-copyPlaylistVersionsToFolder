# Copyright (c) 2013 Shotgun Software Inc.
#
# CONFIDENTIAL AND PROPRIETARY
#
# This work is provided "AS IS" and subject to the Shotgun Pipeline Toolkit
# Source Code License included in this distribution package. See LICENSE.
# By accessing, using, copying or modifying this work you indicate your
# agreement to the Shotgun Pipeline Toolkit Source Code License. All rights
# not expressly granted therein are reserved by Shotgun Software Inc.

"""
App that copies all of the versions in the chosen playlist to a dated folder in the folder structure.
"""

import tank
import os
import re
import glob
import traceback
import datetime
import filecmp
from shutil import copy


PREVIEW = 1
LIGHT = 2
HEAVY = 3


class CopyPlaylistVersionsToFolder(tank.platform.Application):
    all_files = []
    copied = []
    not_copied = []
    missing = []
    already_existing = []

    def init_app(self):
        deny_permissions = self.get_setting("deny_permissions")
        deny_platforms = self.get_setting("deny_platforms")

        p = {"title": "Copy Playlist Files to Folder (Exc. Image Sequences)",
             "deny_permissions": deny_permissions,
             "deny_platforms": deny_platforms,
             "supports_multiple_selection": False}

        self.engine.register_command("copyPlaylistVersionsToFolder_light",
                                     self.copyPlaylistVersionsToFolder_light,
                                     p)

        p = {"title": "Copy Playlist Files to Folder (Inc. Image Sequences)",
             "deny_permissions": deny_permissions,
             "deny_platforms": deny_platforms,
             "supports_multiple_selection": False}

        self.engine.register_command("copyPlaylistVersionsToFolder_heavy",
                                     self.copyPlaylistVersionsToFolder_heavy,
                                     p)

        p = {"title": "Copy Playlist Files to Folder (Preview Mode)",
             "deny_permissions": deny_permissions,
             "deny_platforms": deny_platforms,
             "supports_multiple_selection": False}

        self.engine.register_command("copyPlaylistVersionsToFolder_preview",
                                     self.copyPlaylistVersionsToFolder_preview,
                                     p)

    def returnVersionNumberIntFromStringOrNone(self, fileString):
        regex = "_[vV]\d+"
        result = re.search(regex, fileString)
        if not result:
            return None
        versionStringMatch = result.group(0)
        intVersion = int(versionStringMatch[2:])
        return intVersion

    def copyPlaylistVersionsToFolder_light(self, entity_type, entity_ids):
        self.copyPlaylistVersionsToFolder(entity_type,
                                          entity_ids, mode=LIGHT)

    def copyPlaylistVersionsToFolder_heavy(self, entity_type, entity_ids):
        self.copyPlaylistVersionsToFolder(entity_type,
                                          entity_ids, mode=HEAVY)

    def copyPlaylistVersionsToFolder_preview(self, entity_type, entity_ids):
        self.copyPlaylistVersionsToFolder(entity_type,
                                          entity_ids, mode=PREVIEW)

    def copyPlaylistVersionsToFolder(self, entity_type, entity_ids, mode=PREVIEW):
        try:
            if mode == PREVIEW:
                self.log_info('==================== PREVIEW MODE no files copied. ====================')
                self.log_info('')
            playlist = self.get_playlist(entity_type, entity_ids)
            versions = self.get_playlist_versions(playlist)
            published_files = self.get_published_files(versions)
            published_files.extend(self.get_playlist_published_files(playlist))
            self.copy_files_to_playlist_location(playlist, published_files, mode)
            self.log_info("")
            if mode != PREVIEW:
                self.update_version_info(playlist, versions)
            self.log_info("")
            self.log_info("Finished")
            # self.log_info("Total files found: %d" % len(self.all_files))
            self.log_info("Errors: %d" % len(self.missing))
            self.log_info("Successes: %d" % len(self.copied))
            # self.log_info("Already existing: %d" % len(self.already_existing))
            if mode == PREVIEW:
                self.log_info('')
                self.log_info('==================== PREVIEW MODE no files copied. ====================')
        except Exception, e:
            self.log_exception(traceback.format_exc())
            self.log_exception(str(e))

    def update_version_info(self, playlist, versions):
        for version in versions:
            today = datetime.date.today()
            sendDate = today.strftime('%Y-%m-%d')
            update_data = {'sg_sent_to': playlist['sg_recipient'],
                           'sg_send_date': sendDate}

            self.log_info("Updating send_date and sent_to on %s" % (version['name']))
            self.tank.shotgun.update('Version', version['id'], update_data)

    def get_playlist(self, entity_type, entity_ids):
        context = self.tank.context_from_entity(entity_type, entity_ids[0])
        playlistID = context.entity['id']
        result = self.tank.shotgun.find_one(
            "Playlist", [['id', 'is', playlistID]], ['sg_recipient', 'code'])
        if not result.get('sg_recipient'):
            raise Exception("Playlist has no recipient")
        return result

    def get_playlist_published_files(self, playlist):
        filters = [
            ['playlist_sg_published_files_playlists', 'is', {'type': 'Playlist', 'id': playlist['id']}]]
        fields = ['path',
                  'sg_publish_path',
                  'code']
        published_files = self.tank.shotgun.find(
            'PublishedFile', filters, fields)
        return published_files

    def get_playlist_versions(self, playlist):
        filters = [
            ['playlist', 'is', {'type': 'Playlist', 'id': playlist['id']}]]
        fields = ['playlist.Playlist.code',
                  'sg_sort_order',
                  'version',
                  'version.Version.code']
        versionConnections = self.tank.shotgun.find(
            'PlaylistVersionConnection', filters, fields)
        versions = []
        for connection in versionConnections:
            versions.append(connection['version'])
        return versions

    def get_published_files(self, versions):
        published_files = []
        for version in versions:
            published_files += self.tank.shotgun.find("PublishedFile",
                                                      [['version.Version.id', 'is', version['id']],
                                                       ['sg_internal_only', 'is_not', True]],
                                                      ['sg_publish_path',
                                                       'downstream_published_files',
                                                       'code'])
        downstream_published_files = [] 
        for published_file in published_files:
            if published_file.get('downstream_published_files'):
                for downstream_published_file in published_file['downstream_published_files']:
                    downstream_published_files += self.tank.shotgun.find("PublishedFile",
                                                                          [['id', 'is', downstream_published_file['id']],
                                                                           ['sg_internal_only', 'is_not', True]],
                                                                          ['sg_publish_path',
                                                                           'code'])
        return published_files + downstream_published_files

    def copy_files_to_playlist_location(self, playlist, published_files, mode=PREVIEW):
        output_folder = self.get_output_folder(playlist)
        filepaths = self.get_filepath_list(published_files)
        self.log_info("For playlist %s :" % playlist['code'])
        self.log_info("")
        self.log_info("Copying the following files into %s:" % output_folder)
        self.log_info("")
        for path in filepaths:
            try:
                if self.copy_file(path, output_folder, mode):
                    self.log_info("Success: %s" % os.path.basename(path))
                    self.copied.append(file)
            except Exception as e:
                self.log_info("Error: %s" % os.path.basename(path))
                self.missing.append(file)

    def get_output_folder(self, playlist):
        projectPath = self.tank.project_path
        dailiesDir = os.path.join(projectPath, 'client_io', 'out')

        playlistDir = os.path.join(dailiesDir, playlist['code'])
        return playlistDir

    def get_filepath_list(self, published_files):
        paths = []
        for published_file in published_files:
            if published_file.get('sg_publish_path'):
                p = self.get_localised_path(published_file['sg_publish_path'])
                if p:
                    paths.append(p)
            else:
                self.log_info("Cannot find publish path for %s" % published_file['code'])
                # exit()
                # paths.append(published_file['sg_publish_path']['local_path'])
            # elif published_file.get('path'):
            #     p = self.get_localised_path(published_file['path'])
            #     if p:
            #         paths.append(p)
            #     # paths.append(published_file['path']['local_path'])
        return paths

    def get_localised_path(self, path_obj):
        if path_obj.get("local_path"):
            return path_obj["local_path"]
        elif path_obj.get("url"):
            url = path_obj.get("url")
            nuPath = url.replace("file://", "//")
            if os.name == "posix":
                nuPath = nuPath.replace("\\", "/")
                nuPath = nuPath.replace("Y:/", "/Volumes/FilmShare/")
                nuPath = nuPath.replace("//192.168.50.10/filmshare/", "/Volumes/FilmShare/")
                nuPath = nuPath.replace("//192.168.50.10/FILMSHARE/", "/Volumes/FilmShare/")
                nuPath = nuPath.replace("//192.168.50.10/FilmShare/", "/Volumes/FilmShare/")
                nuPath = nuPath.replace("//192.168.50.10/Filmshare/", "/Volumes/FilmShare/")
                nuPath = nuPath.replace("//ldn-fs1/projects/", "/Volumes/projects/")
            else:
                nuPath = nuPath.replace("/", "\\")
                nuPath = nuPath.replace("\\Volumes\\projects\\", "\\\\ldn-fs1\\projects\\")
                nuPath = nuPath.replace("\\Volumes\\FilmShare\\", "Y:\\")
                nuPath = nuPath.replace("\\Volumes\\Filmshare\\", "Y:\\")
                nuPath = nuPath.replace("\\Volumes\\filmshare\\", "Y:\\")
                nuPath = nuPath.replace("\\Volumes\\FILMSHARE\\", "Y:\\")
                nuPath = nuPath.replace("\\\\192.168.50.10\\filmshare\\", "Y:\\")
                nuPath = nuPath.replace("\\\\192.168.50.10\\FILMSHARE\\", "Y:\\")
                nuPath = nuPath.replace("\\\\192.168.50.10\\FilmShare\\", "Y:\\")
                nuPath = nuPath.replace("\\\\192.168.50.10\\Filmshare\\", "Y:\\")
            return nuPath

    def copy_file(self, source, dest_folder, mode=PREVIEW):
        files = [source]
        is_seq = self.is_sequence(source)
        if is_seq:
            if mode == LIGHT:
                return False
            files = self.get_sequence_files(source)
            if len(files) == 0:
                self.log_exception("MISSING FILE: " + str(file))
                self.missing.append(file)
            dest_folder = os.path.join(dest_folder, self.get_sequence_sub_folder(source))
        if not os.path.exists(dest_folder) and mode != PREVIEW:
            os.makedirs(dest_folder)
        if len(files) == 0:
            return False
        for file in files:
            self.all_files.append(file)
            nu_path = os.path.join(dest_folder, os.path.basename(file))
            if os.path.exists(nu_path) and filecmp.cmp(file, nu_path, True):
                self.already_existing.append(file)
            else:
                if mode != PREVIEW:
                    if os.path.exists(file):
                        copy(file, nu_path)
                    else:
                        self.log_exception("MISSING FILE: " + str(file))
                        return False
        return True

    def is_sequence(self, path):
        pattern = re.compile(".*%\d+d\..*")
        return bool(pattern.match(path))

    def get_sequence_files(self, path):
        FRAME_REGEX = re.compile("(.*)(%\d+d)(.+)$", re.IGNORECASE)
        search = re.search(FRAME_REGEX, path)
        frames = []
        if search and len(search.groups()) == 3:
            frames = glob.glob(search.group(1) + "*" + search.group(3))
        return frames

    def get_sequence_sub_folder(self, path):
        FRAME_REGEX = re.compile("(.*).(%\d+d)(.+)$", re.IGNORECASE)
        search = re.search(FRAME_REGEX, path)
        sub_folder = os.path.basename(search.group(1))
        return sub_folder
