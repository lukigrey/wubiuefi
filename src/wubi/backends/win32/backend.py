# Copyright (c) 2008 Agostino Russo
#
# Written by Agostino Russo <agostino.russo@gmail.com>
#
# This file is part of Wubi the Win32 Ubuntu Installer.
#
# Wubi is free software; you can redistribute it and/or modify
# it under 5the terms of the GNU Lesser General Public License as
# published by the Free Software Foundation; either version 2.1 of
# the License, or (at your option) any later version.
#
# Wubi is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#

import sys
import os
import _winreg
import ConfigParser
import subprocess
import ctypes
#import platform
from drive import Drive
import registry
from memory import get_total_memory_mb
from wubi.backends.common import Backend, run_command, replace_line_in_file, read_file, write_file
import mappings
import logging
import shutil
log = logging.getLogger('WindowsBackend')


class WindowsBackend(Backend):
    '''
    Win32-specific backend
    '''

    def __init__(self, *args, **kargs):
        Backend.__init__(self, *args, **kargs)
        self.info.iso_extractor = os.path.join(self.info.bindir, '7z.exe')
        log.debug('7z=%s' % self.info.iso_extractor)
        self.cache = {}

    def fetch_host_info(self):
        log.debug("Fetching host info...")
        self.info.registry_key = self.get_registry_key()
        self.info.windows_version = self.get_windows_version()
        self.info.windows_version2 = self.get_windows_version2()
        self.info.windows_sp = self.get_windows_sp()
        self.info.windows_build = self.get_windows_build()
        self.info.timezone = self.get_timezone()
        self.info.host_username = self.get_windows_username()
        self.info.user_full_name = self.get_windows_user_full_name()
        self.info.user_directory = self.get_windows_user_dir()
        self.info.windows_language_code = self.get_windows_language_code()
        self.info.windows_language = self.get_windows_language()
        self.info.processor_name = self.get_processor_name()
        self.info.bootloader = self.get_bootloader(self.info.windows_version)
        self.info.system_drive = self.get_system_drive()
        self.info.drives = self.get_drives()

    def select_target_dir(self):
        target_dir = os.path.join(self.info.target_drive.path + '\\', self.info.application_name)
        target_dir.replace(' ', '_')
        target_dir.replace('__', '_')
        gold_target_dir = target_dir
        if os.path.exists(target_dir) \
        and self.info.previous_target_dir \
        and os.path.isdir(self.info.previous_target_dir) \
        and self.info.previous_target_dir != target_dir:
            for i in range(2, 1000):
                target_dir = gold_target_dir + '.' + str(i)
                if not os.path.exists(target_dir):
                    break
        self.info.target_dir = target_dir
        if self.info.previous_target_dir \
        and os.path.isdir(self.info.previous_target_dir):
            os.rename(self.info.previous_target_dir, self.info.target_dir)
        log.info('Installing into %s' % target_dir)

    def uncompress_files(self, associated_task):
        command1 = ['compact', os.path.join(self.info.target_dir), '/U', '/S', '/A', '/F']
        command2 = ['compact', os.path.join(self.info.target_dir,'*.*'), '/U', '/S', '/A', '/F']
        for command in [command1,command2]:
            log.debug(" ".join(command))
            try:
                run_command(command)
            except Exception, err:
                log.error(err)

    def create_uninstaller(self, associated_task):
        uninstaller_name = 'uninstall-%s.exe'  % self.info.application_name
        uninstaller_name.replace(' ', '_')
        uninstaller_name.replace('__', '_')
        uninstaller_path = os.path.join(self.info.target_dir, uninstaller_name)
        log.debug('Copying uninstaller %s -> %s' % (self.info.original_exe, uninstaller_path))
        shutil.copyfile(self.info.original_exe, uninstaller_path)
        registry.set_value('HKEY_LOCAL_MACHINE', self.info.registry_key, 'UninstallString', uninstaller_path)

    def create_virtual_disks(self, associated_task):
        pass #TBD

    def eject_cd(self, associated_task):
        #platform specific
        #IOCTL_STORAGE_EJECT_MEDIA 0x2D4808
        #FILE_SHARE_READ 1
        #FILE_SHARE_WRITE 2
        #FILE_SHARE_READ|FILE_SHARE_WRITE 3
        #GENERIC_READ 0x80000000
        #OPEN_EXISTING 3
        if not self.info.cd_path:
            return
        cd_handle = windll.kernel32.CreateFile(r'\\\\.\\' + self.info.cd_path, 0x80000000, 3, 0, 3, 0, 0)
        log.debug('Ejecting cd_handle=%s for drive=%s' % (cd_handle, self.info.cd_path))
        if cd_handle:
            x = ctypes.c_int()
            result = windll.kernel32.DeviceIoControl(cd_handle, 0x2D4808, 0, 0, 0, 0, ctypes.byref(x), 0)
            log.debug('EjectCD DeviceIoControl exited with code %s (1==success)' % result)
            windll.kernel32.CloseHandle(cd_handle)

    def reboot(self):
        command = ['shutdown', '-r', '-t', '00']
        if self.info.test:
            log.info("Test mode, skipping reboot, normally the following command would be run: %s" % " ".join(command))
        else:
            run_command(command) #TBD make async

    def copy_installation_files(self, associated_task):
        self.info.custominstall = os.path.join(self.info.installdir, 'custom-installation')
        src = os.path.join(self.info.datadir, 'custom-installation')
        log.debug('Copying %s -> %s' % (src, self.info.custominstall))
        shutil.copytree(src, self.info.custominstall)
        src = os.path.join(self.info.datadir, 'winboot')
        dest = os.path.join(self.info.target_dir, 'winboot')
        log.debug('Copying %s -> %s' % (src, dest))
        shutil.copytree(src, dest)
        dest = os.path.join(self.info.custominstall, 'hooks', 'failure-command.sh')
        msg='The installation failed. Logs have been saved in: %s.' \
            '\n\nNote that in verbose mode, the logs may include the password.' \
            '\n\nThe system will now reboot.'
        msg = msg % os.path.join(self.info.installdir, 'installation-logs.zip')
        replace_line_in_file(dest, 'msg=', "msg='%s'" % msg)

    def get_windows_version2(self):
        windows_version2 = registry.get_value(
                'HKEY_LOCAL_MACHINE',
                'SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion',
                'ProductName')
        log.debug('windows_version2=%s' % windows_version2)
        return windows_version2

    def get_windows_sp(self):
        windows_sp = registry.get_value(
                'HKEY_LOCAL_MACHINE',
                'SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion',
                'CSDVersion')
        log.debug('windows_sp=%s' % windows_sp)
        return windows_sp

    def get_windows_build(self):
        windows_build  = registry.get_value(
                'HKEY_LOCAL_MACHINE',
                'SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion',
                'CurrentBuildNumber')
        log.debug('windows_build=%s' % windows_build)
        return windows_build

    def get_processor_name(self):
        processor_name = registry.get_value(
            'HKEY_LOCAL_MACHINE',
            'HARDWARE\\DESCRIPTION\\System\\CentralProcessor\\0',
            'ProcessorNameString')
        log.debug('processor_name=%s' %processor_name)
        return processor_name

    def get_timezone(self):
        timezone = "" #TBD
        log.debug('timezone=%s' % timezone)
        return timezone

    def get_windows_version(self):
        windows_version = None
        full_version = sys.getwindowsversion()
        major, minor, build, platform, txt = full_version
        #platform.platform(), platform.system(), platform.release(), platform.version()
        if platform == 0:
            version = 'win32'
        elif platform == 1:
            if major == 4:
                if minor == 0:
                    version = '95'
                elif minor == 10:
                    version = '98'
                elif minor == 90:
                    version = 'me'
        elif platform == 2:
            if major == 4:
                version = 'nt'
            elif major == 5:
                if minor == 0:
                    version = '2000'
                elif minor == 1:
                    version = 'xp'
                elif minor == 2:
                    version = '2003'
            elif major == 6:
                version = 'vista'
        log.debug('windows version=%s' % version)
        return version

    def get_bootloader(self, windows_version):
        if windows_version in ['vista', '2008']:
            bootloader = 'vista'
        elif windows_version in ['nt', 'xp', '2000', '2003']:
            bootloader = 'xp'
        elif windows_version in ['95', '98']:
            bootloader = '98'
        else:
            bootloader = None
        log.debug('bootloader=%s' % bootloader)
        return bootloader

    def get_networking_info(self):
        return NotImplemented
        #~ win32com.client.Dispatch('WbemScripting.SWbemLocator') but it doesn't
        #~ seem to function on win 9x. This script is intended to detect the
        #~ computer's network configuration (gateway, dns, ip addr, subnet mask).
        #~ Does someone know how to obtain those informations on a win 9x ?
        #~ Windows 9x came without support for WMI. You can download WMI Core from
        #~ http://www.microsoft.com/downloads/details.aspx?FamilyId=98A4C5BA-337B-4E92-8C18-A63847760EA5&displaylang=en
        #~ although the implementation is quite limited

    def get_drives(self):
        drives = []
        for letter in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ':
            drive = Drive(letter)
            if drive.type:
                log.debug('drive=%s'% str(drive))
                drives.append(drive)
        return drives

    def get_uninstaller_path(self):
        uninstaller_path = registry.get_value('HKEY_LOCAL_MACHINE', self.info.registry_key, 'UninstallString')
        log.debug('uninstaller_path=%s' % uninstaller_path)
        return uninstaller_path

    def get_registry_key(self):
        registry_key = 'Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\'  + self.info.application_name
        log.debug('registry_key=%s' % registry_key)
        return registry_key

    def get_windows_language_code(self):
        #~ windows_language_code = registry.get_value(
                #~ 'HKEY_CURRENT_USER',
                #~ '\\Control Panel\\International',
                #~ 'sLanguage')
        windows_language_code = mappings.language2n.get(self.info.language[:2])
        log.debug('windows_language_code=%s' % windows_language_code)
        if not windows_language_code:
            windows_language_code = 1033 #English
        return windows_language_code

    def get_windows_language(self):
        windows_language = mappings.n2fulllanguage.get(self.info.windows_language_code)
        log.debug('windows_language=%s' % windows_language)
        if not windows_language:
            windows_language = 'English'
        return windows_language

    def get_total_memory_mb(self):
        total_memory_mb = get_total_memory_mb()
        log.debug('total_memory_mb=%s' % total_memory_mb)
        return total_memory_mb

    def get_windows_username(self):
        windows_username = os.getenv('username')
        log.debug('windows_username=%s' % windows_username)
        return windows_username

    def get_windows_user_full_name(self):
        user_full_name = os.getenv('username') #TBD
        log.debug('user full name=%s' % user_full_name)
        return user_full_name

    def get_windows_user_dir(self):
        user_directory = os.getenv('username') #TBD get user directory
        log.debug('user_directory=%s' % user_directory)
        return user_directory

    def get_keyboard_layout(self):
        keyboard_layout = ctypes.windll.user32.GetKeyboardLayout(0)
        log.debug('keyboard_layout=%s' % keyboard_layout)
        return keyboard_layout

        #~ lower word is the locale identifier (higher word is a handler to the actual layout)
        #~ IntOp $hkl $0 & 0xFFFFFFFF
        #~ IntFmt $hkl '0x%08X' $hkl
        #~ IntOp $localeid $0 & 0x0000FFFF
        #~ IntFmt $localeid '0x%04X' $localeid
        #~ ReadINIStr $layoutcode $PLUGINSDIR\data\keymaps.ini 'keymaps' '$localeid'
        #~ ReadINIStr $keyboardvariant $PLUGINSDIR\data\variants.ini 'hkl2variant' '$hkl'
        #~ #${debug} 'hkl=$hkl, localeid=$localeid, layoutcode=$layoutcode, keyboardvariant=$keyboardvariant'
        #~ ${if} '$layoutcode' != ''
        #~ return
        #~ ${endif}
        #~ safetynet:
        #~ StrCpy $layoutcode '$country'
        #~ ${StrFilter} '$layoutcode' '-' '' '' '$layoutcode' #lowercase
        #~ ${debug} 'LayoutCode=$LayoutCode'

    def get_system_drive(self):
        system_drive = os.getenv('SystemDrive')
        system_drive = Drive(system_drive)
        log.debug('system_drive=%s' % system_drive)
        return system_drive

    def detect_proxy(self):
        '''
        https://bugs.edge.launchpad.net/wubi/+bug/135815
        '''
        #TBD

    def extract_file_from_iso(self, iso_path, file_path, output_dir=None, overwrite=False):
        '''
        platform specific
        '''
        iso_path = os.path.abspath(iso_path)
        file_path = os.path.normpath(file_path)
        if not output_dir:
            output_dir = tempfile.gettempdir()
        output_file = os.path.join(output_dir, os.path.basename(file_path))
        if os.path.exists(output_file):
            if overwrite:
                os.unlink(output_file)
            else:
                raise Exception('Cannot overwrite %s' % output_file)
        command = [self.info.iso_extractor, 'e', '-i!' + file_path, '-o' + output_dir, iso_path]
        try:
            output = run_command(command)
        except Exception, err:
            log.exception(err)
            output_file = None
        if output_file and os.path.isfile(output_file):
            return output_file

    def get_usb_search_paths(self):
        '''
        Used to detect ISOs in USB keys
        '''
        return [drive.path for drive in self.info.drives] #TBD only look in USB devices

    def get_iso_search_paths(self):
        '''
        Gets default paths scanned for CD and ISOs
        '''
        paths = []
        paths += [os.path.dirname(self.info.original_exe)]
        paths += [self.info.previous_backupdir] #TBD search backup folder
        paths += [drive.path for drive in self.info.drives]
        paths += [os.environ.get('Desktop', None)]
        paths += ['/home/vm/cd'] #TBD quick test
        paths = [os.path.abspath(p) for p in paths]
        return paths

    def verify_signature(self, file, signature, associated_task=None):
        #TBD
        return True

    def get_cd_search_paths(self):
        return [drive.path for drive in self.info.drives] # if drive.type == 'cd']

    def get_iso_file_names(self, iso_path):
        iso_path = os.path.abspath(iso_path)
        if iso_path in self.cache:
            return self.cache[iso_path]
        else:
            self.cache[iso_path] = None
        command = [self.info.iso_extractor,'l',iso_path]
        try:
            output = run_command(command)
        except Exception, err:
            log.exception(err)
            log.debug('command >>%s' % ' '.join(command))
            output = None
        if not output: return []
        lines = output.split(os.linesep)
        if lines < 10: return []
        lines = lines[7:-3]
        file_info = [line.split() for line in lines]
        file_names = [os.path.normpath(x[-1]) for x in file_info]
        self.cache[iso_path] = file_names
        return file_names

    def remove_registry_key(self):
        registry.delete_key(
            'HKEY_LOCAL_MACHINE',
            self.info.registry_key)

    def modify_bootloader(self):
        for drive in self.info.drives:
            if drive not in ('removable', 'hd'):
                continue
            if self.info.bootloader == 'xp':
                self.modify_bootini(path)
            elif self.info.bootloader == '98':
                self.modify_configsys(path)
            elif self.info.bootloader == 'vista':
                self.modify_bcd(path)

    def undo_bootloader(self, associated_task):
        winboot_files = ['wubildr', 'wubildr.mbr', 'wubildr.exe']
        for drive in self.info.drives:
            self.undo_bootini(drive, associated_task)
            self.undo_configsys(drive, associated_task)
            self.undo_bcd(associated_task)
        for f in winboot_files:
            f = os.path.join(drive.path, '/', f)
            if os.path.isfile(f):
                os.unlink(f)

    def modify_bootini(self, drive, associated_task):
        log.debug("modify_bootini %s" % drive)
        bootini = os.path.join(drive.path, '/', 'boot.ini')
        if not os.path.isfile(bootini):
            return
        shutil.copy(os.path.join(self.info.datadir, 'winboot', 'wubildr'),  drive.path)
        shutil.copy(os.path.join(self.info.datadir, 'winboot', 'wubildr.mbr'),  drive.path)
        run_command(['attrib', '-R', '-S', '-H', bootini])
        ini = ConfigParser.ConfigParser()
        ini.read(bootini)
        ini.set('boot loader', 'timeout', 10)
        ini.set('operating systems', 'c:\wubildr.mbr', self.info.distro.name)
        f = open(bootini, 'w')
        ini.write(f)
        f.close()
        run_command(['attrib', '+R', '+S', '+H', bootini])

    def undo_bootini(self, drive, associated_task):
        log.debug("undo_bootini %s" % drive)
        bootini = os.path.join(drive.path, '/', 'boot.ini')
        if not os.path.isfile(bootini):
            return
        run_command(['attrib', '-R', '-S', '-H', bootini])
        ini = ConfigParser.ConfigParser()
        ini.read(bootini)
        ini.remove_option('operating systems', 'c:\wubildr.mbr')
        f = open(bootini, 'w')
        ini.write(f)
        f.close()
        run_command(['attrib', '+R', '+S', '+H', bootini])

    def modify_configsys(self, drive, associated_task):
        log.debug("modify_configsys %s" % drive)
        configsys = os.path.join(drive.path, '/', 'config.sys')
        if not os.path.isfile(configsys):
            return
        shutil.copy(os.path.join(self.info.datadir, 'winboot', 'wubildr.exe'),  drive.path)
        run_command(['attrib', '-R', '-S', '-H', configsys])
        config = read_file(configsys)
        if 'REM WUBI MENU START\n' in config:
            log.debug("Configsys has already been modified")
            return

        config += '''
        REM WUBI MENU START
        [menu]
        menucolor=15,0
        menuitem=windows,Windows
        menuitem=wubildr,$distro
        menudefault=windows,10
        [wubildr]
        device=wubildr.exe
        [windows]

        REM WUBI MENU END
        '''
        write_file(configsys, config)
        run_command(['attrib', '+R', '+S', '+H', configsys])

    def undo_configsys(self, drive, associated_task):
        log.debug("undo_configsys %s" % drive)
        configsys = os.path.join(drive.path, '/', 'config.sys')
        if not os.path.isfile(configsys):
            return
        run_command(['attrib', '-R', '-S', '-H', configsys])
        config = read_file(configsys)
        s = config.find('REM WUBI MENU START\n')
        e = config.find('REM WUBI MENU END\n')
        if s > 0 and e > 0:
            e += len('REM WUBI MENU END')
        config = config[:s] + config[e:]
        write_file(configsys, config)
        run_command(['attrib', '+R', '+S', '+H', configsys])

    def modify_bcd(self, drive, associated_task):
        log.debug("modify_bcd %s" % drive)

        if drive is self.info.system_drive \
        or drive.path == "C:" \
        or drive.path == os.environ('systemroot')[:2]:
            shutil.copy(os.path.join(self.info.datadir, 'winboot', 'wubildr'),  drive.path)
            shutil.copy(os.path.join(self.info.datadir, 'winboot', 'wubildr.mbr'),  drive.path)

        bcdedit = os.path.join(os.getenv('SystemDrive'), 'bcdedit.exe')
        if not os.path.isfile(bcdedit):
            bcdedit = os.path.join(os.environ('systemroot'), 'sysnative', 'bcdedit.exe')
        if not os.path.isfile(bcdedit):
            log.error("Cannot find bcdedit")
            return
        if registry.get_key('HKEY_LOCAL_MACHINE', self.info.registry_key, 'VistaBootDrive'):
            log.debug("BCD has already been modified")
            return

        command = [bcdedit, '/create', '/d', '"%s"' % self.info.distro.name, '/application', 'bootsector']
        id = run_command(command)
        id = id[id.index('{'):id.index('}')+1]
        command = [bcdedit, '/set', id,  'device', 'partition=%s' + self.info.target_drive.path]
        run_command(command)
        command = [bcdedit, '/set', id,  'path', 'wubildr.mbr']
        run_command(command)
        command = [bcdedit, ' /displayorder', id,  '/addlast']
        run_command(command)
        command = [bcdedit, ' /timeout', 10]
        run_command(command)
        registry.set_key(
            'HKEY_LOCAL_MACHINE',
            self.info.registry_key,
            'VistaBootDrive',
            id)

    def choose_disk_sizes(self, associated_task):
        total_size_mb = self.info.installation_size_mb
        home_size_mb = 0
        usr_size_mb = 0
        swap_size_mb = 256
        root_size_mb = total_size_mb - swap_size_mb
        if self.info.target_drive.filesystem == "vfat":
            if root_size_mb > 8500:
                home_size_mb = root_size_mb - 8000
                usr_size_mb = 4000
                root_size_mb = 4000
            elif root_size_mb > 5500:
                usr_size_mb = 4000
                root_size_mb -= 4000
            elif root_size_mb > 4000:
                usr_size_mb = root_size_mb - 1500
                root_size_mb = 1500
            if home_size_mb > 4000:
               home_size_mb = 4000
        self.info.home_size_mb = home_size_mb
        self.info.usr_size_mb = usr_size_mb
        self.info.swap_size_mb = swap_size_mb
        self.info.root_size_mb = root_size_mb
        log.debug("total size=%s\n  root=%s\n  swap=%s\n  home=%s\n  usr=%s" % (total_size_mb, root_size_mb, swap_size_mb, home_size_mb, usr_size_mb))

    def undo_bcd(self, associated_task):
        bcdedit = os.path.join(os.getenv('SystemDrive'), 'bcdedit.exe')
        if not os.path.isfile(bcdedit):
            bcdedit = os.path.join(os.getenv('SystemRoot'), 'sysnative', 'bcdedit.exe')
        if not os.path.isfile(bcdedit):
            log.error("Cannot find bcdedit")
            return
        id = registry.get_key(
            'HKEY_LOCAL_MACHINE',
            self.info.registry_key,
            'VistaBootDrive')
        if not id:
            log.debug("Could not find bcd id")
            return
        log.debug("Removing bcd entry %s" % id)
        command = [bcdedit, '/delete', id , '/f']
        run_command(command)