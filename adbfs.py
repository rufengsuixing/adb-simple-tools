"""
fs.adbfs
========

ADBFS is a filesystem for accessing an ADB

"""

__all__ = ['ADBFS']

import sys

import fs
from fs.base import *
from fs.errors import *
from fs.path import pathsplit, abspath, dirname, recursepath, normpath, pathjoin, isbase, forcedir
from fs import iotools
import subprocess
import os ,tempfile



import threading
import datetime
import calendar

from socket import error as socket_error
from fs.local_functools import wraps

import six
from six import PY3, b

if PY3:
    from six import BytesIO as StringIO
else:
    try:
        from io import StringIO
    except ImportError:
        from io import StringIO

import time


# -----------------------------------------------
# Modified from http://www.clapper.org/software/python/grizzled/
# -----------------------------------------------

class Enum(object):
    def __init__(self, *names):
        self._names_map = dict((name, i) for i, name in enumerate(names))

    def __getattr__(self, name):
        return self._names_map[name]

MTIME_TYPE = Enum('UNKNOWN', 'LOCAL', 'REMOTE_MINUTE', 'REMOTE_DAY')
"""
``MTIME_TYPE`` identifies how a modification time ought to be interpreted
(assuming the caller cares).

    - ``LOCAL``: Time is local to the client, granular to (at least) the minute
    - ``REMOTE_MINUTE``: Time is local to the server and granular to the minute
    - ``REMOTE_DAY``: Time is local to the server and granular to the day.
    - ``UNKNOWN``: Time's locale is unknown.
"""

ID_TYPE = Enum('UNKNOWN', 'FULL')
"""
``ID_TYPE`` identifies how a file's identifier should be interpreted.

    - ``FULL``: The ID is known to be complete.
    - ``UNKNOWN``: The ID is not set or its type is unknown.
"""

# ---------------------------------------------------------------------------
# Globals
# ---------------------------------------------------------------------------

current_year = time.localtime().tm_year

# ---------------------------------------------------------------------------
# Classes
# ---------------------------------------------------------------------------

class ADBListData(object):
    """
    The `ADBListDataParser` class's ``parse_line()`` method returns an
    instance of this class, capturing the parsed data.

    :IVariables:
        name : str
            The name of the file, if parsable
        try_cwd : bool
            ``True`` if the entry might be a directory , ``False`` if it
            cannot possibly be a directory.
        try_retr : bool
            ``True`` if the entry might be a retrievable file , ``False`` if it
            cannot possibly be a file.
        size : long
            The file's size, in bytes
        mtime : long
            The file's modification time, as a value that can be passed to
            ``time.localtime()``.
        mtime_type : `MTIME_TYPE`
            How to interpret the modification time. See `MTIME_TYPE`.
        id : str
            A unique identifier for the file. The unique identifier is unique
            on the *server*. On a Unix system, this identifier might be the
            device number and the file's inode; on other system's, it might
            be something else. It's also possible for this field to be ``None``.
        id_type : `ID_TYPE`
            How to interpret the identifier. See `ID_TYPE`.
   """

    def __init__(self, raw_line):
        self.raw_line = raw_line
        self.name = None
        self.try_cwd = False
        self.try_retr = False
        self.size = 0
        self.mtime_type = MTIME_TYPE.UNKNOWN
        self.mtime = 0
        self.id_type = ID_TYPE.UNKNOWN
        self.id = None

class ADBListDataParser(object):
    """
    An ``ADBListDataParser`` object can be used to parse one or more lines
    that were retrieved by an ADB li -l command that was sent to a remote
    server.
    """
    def __init__(self):
        pass

    def parse_line(self, adb_list_line):
        """
        Parse a line from an shell ls -l command.

        :Parameters:
            adb_list_line : str
                The line of output

        :rtype: `ADBListData`
        :return: An `ADBListData` object describing the parsed line, or
                 ``None`` if the line could not be parsed. Note that it's
                 possible for this method to return a partially-filled
                 `ADBListData` object (e.g., one without a name).
        """
        buf = adb_list_line
        return self._parse_unix_style(buf)
    
    def _parse_unix_style(self, buf):
        result = ADBListData(buf)
        c = buf[0]
        tokens = buf.split()
        if c == 'd':
            result.try_cwd = True
            size=0
            datestr=tokens[3]+' '+tokens[4]
            #name=tokens[5]
            result.name=buf.split(maxsplit=6)[-1]
        elif c == '-':
            result.try_retr = True
            size=int(tokens[3])
            datestr=tokens[4]+' '+tokens[5]
            result.name=buf.split(maxsplit=7)[-1]
        elif c == 'l':
            result.try_retr = True
            result.try_cwd = True
            size=0
            datestr=tokens[3]+' '+tokens[4]
            name=buf.split(maxsplit=5)[-1]
            i = 0
            while (i + 3) < len(name):
                if name[i:i+4] == ' -> ':
                    result.target = name[i+4:]
                    result.name = name[:i]
                    break
                i += 1
        elif c=='c':
            result.try_retr = True
            size=0
            datestr=tokens[5]+' '+tokens[6]
            result.name=buf.split(maxsplit=8)[-1]
        else:
            return result
        #result.name
        result.mtime_type = MTIME_TYPE.REMOTE_MINUTE
        result.size = size
        result.mtime=time.mktime(time.strptime(datestr,'%Y-%m-%d %H:%M'))

        return result

# ---------------------------------------------------------------------------
# Public Functions
# ---------------------------------------------------------------------------

def parse_adb_list_line(adb_list_line):
    """
    Convenience function that instantiates an `ADBListDataParser` object
    and passes ``adb_list_line`` to the object's ``parse_line()`` method,
    returning the result.

    :Parameters:
        adb_list_line : str
            The line of output

    :rtype: `ADBListData`
    :return: An `ADBListData` object describing the parsed line, or
             ``None`` if the line could not be parsed. Note that it's
             possible for this method to return a partially-filled
             `ADBListData` object (e.g., one without a name).
    """
    
    return ADBListDataParser().parse_line(adb_list_line)

# ---------------------------------------------------------------------------
# Private Functions
# ---------------------------------------------------------------------------

def fileadberrors(f):
    @wraps(f)
    def deco(self, *args, **kwargs):
        self._lock.acquire()
        try:
            try:
                ret = f(self, *args, **kwargs)
            except Exception as e:
                self.adbfs._translate_exception(args[0] if args else '', e)
        finally:
            self._lock.release()
        return ret
    return deco



class _ADBFile(object):

    """ A file-like that provides access to a file being streamed over adb."""

    blocksize = 1024 * 64

    def __init__(self, adbfs, path, mode):
        if not hasattr(self, '_lock'):
            self._lock = threading.RLock()
        self.adbfs = adbfs
        self.path = normpath(path)
        self.mode = mode
        self.pos = 0
        self.closed = False
        self.file_size = None
        if 'r' in mode or 'a' in mode:
            self.file_size = adbfs.getsize(path)
        rpath = tempfile.mktemp()
        self._cmd_co('adb pull '+self.path+' '+rpath)
        self.tmpop=open(rpath,mode)
        self.change=False
    def _cmd_co(self,command):
        back=subprocess.Popen(command,shell=True,stdout=subprocess.PIPE)
        str=back.communicate()
        back.kill()
        print(str[0].decode('utf-8'))
        return 
    @fileadberrors
    def read(self, size=None):
        print('read '+self.path)
        return self.tmpop.read(size)
        
    @fileadberrors
    def write(self, data):
        print('write')
        self.tmpop.write(data)
        self.change=True
    def __enter__(self):
        return self

    def __exit__(self,exc_type,exc_value,traceback):
        self.close()

    @fileadberrors
    def flush(self):
        self.adbfs._on_file_written(self.path)
        self.tmpop.flush()
    @fileadberrors
    def seek(self, pos, where=fs.SEEK_SET):
        self.tmpop.seek(pos, where)
    @fileadberrors
    def tell(self):
        return self.tmpop.tell()

    @fileadberrors
    def truncate(self, size=None):
        print('truncate')
        self.adbfs._on_file_written(self.path)
        self.tmpop.truncate(size)
        
    @fileadberrors
    def close(self):
        print('closed')
        if self.change==True:
            self.adbfs._on_file_written(self.path)
            self._cmd_co('adb push '+self.tmpop.name+' '+self.path)
        self.tmpop.close()
        self.closed = True

    def __next__(self):
        return self.readline()

    def readline(self, size=None):
        return next(iotools.line_iterator(self, size))

    def __iter__(self):
        return iotools.line_iterator(self)


def adberrors(f):
    @wraps(f)
    def deco(self, *args, **kwargs):
        self._lock.acquire()
        print(f)
        try:
            self._enter_dircache()
            try:
                try:
                    ret = f(self, *args, **kwargs)
                except Exception as e:
                    self._translate_exception(args[0] if args else '', e)
            finally:
                self._leave_dircache()
        finally:
            self._lock.release()
        return ret
    return deco


def _encode(s):
    if isinstance(s, str):
        return s.encode('utf-8')
    return s

class _DirCache(dict):
    def __init__(self):
        super(_DirCache, self).__init__()
        self.count = 0
    def addref(self):
        self.count += 1
        return self.count
    def decref(self):
        self.count -= 1
        return self.count

class ADBFS(FS):

    _meta = { 'thread_safe' : True,
              'network' : True,
              'virtual': False,
              'read_only' : False,
              'unicode_paths' : True,
              'case_insensitive_paths' : False,
              'atomic.move' : True,
              'atomic.copy' : True,
              'atomic.makedir' : True,
              'atomic.rename' : True,
              'atomic.setcontents' : False,
              'file.read_and_write' : False,
              }

    def __init__(self, dircache=True,dircacheall=True,follow_symlinks=False):
        """Connect to a adb.
        :param dircache: If True then directory information will be cached,
            speeding up operations such as `getinfo`, `isdir`, `isfile`, but
            changes to the adb file structure will not be visible until
            :meth:`~fs.adbfs.ADBFS.clear_dircache` is called

        """
        super(ADBFS, self).__init__()
        self.use_dircache = dircache
        self.follow_symlinks = follow_symlinks
        self._lock = threading.RLock()
        self._init_dircache()
        self._cache_hint = False
        if dircacheall==True:
            self._cache_all()
    def _cache_all(self):

        def on_line(line):
            if not isinstance(line, str):
                line = line.decode('utf-8')
            info = parse_adb_list_line(line)
            if info:
                info = info.__dict__
                if info['name'] not in ('.', '..'):
                    dirlist[info['name']] = info
        byline=self._adb_get('ls -l -R')
        for le in byline:
            if le[0]=='.':
                path=le[1:-2]
                dirlist = {}
            else:
                on_line(le)
                self.dircache[path] = dirlist
                self.dircache.addref()
                print('cache',path)
        print(self.dircache.count)
    def _init_dircache(self):
        self.dircache = _DirCache()

    @synchronize
    def cache_hint(self, enabled):
        self._cache_hint = bool(enabled)

    def _enter_dircache(self):
        self.dircache.addref()

    def _leave_dircache(self):
        self.dircache.decref()
        if self.use_dircache:
            pass
        else:
            self.clear_dircache()
        assert self.dircache.count >= 0, "dircache count should never be negative"

    @synchronize
    def _on_file_written(self, path):
        self.refresh_dircache(dirname(path))
    def _adb_get(self,command):
        back=subprocess.Popen('adb shell' ,shell=True,stdin=subprocess.PIPE,stdout=subprocess.PIPE)
        inby=command.encode('utf-8')+b';exit\n'
        back.stdin.write(inby)
        by=back.communicate()[0].decode('utf-8')
        back.kill()
        byline=by.splitlines(False)
        for a in range(0,len(byline)-1):
            if byline[a]=='' and byline[a+1]=='':
                byline=byline[a+2:]
                break
        byline=[a for a in byline if a]
        return byline
    @synchronize
    def _readdir(self, path):
        
        path = abspath(normpath(path))
        if self.dircache.count:
            cached_dirlist = self.dircache.get(path)
            if cached_dirlist:
                print('getcache')
                return cached_dirlist
        dirlist = {}

        def on_line(line):
            if not isinstance(line, str):
                line = line.decode('utf-8')
            info = parse_adb_list_line(line)
            if info:
                info = info.__dict__
                if info['name'] not in ('.', '..'):
                    dirlist[info['name']] = info
        gpath=forcedir(path).replace(r'(',r'\(').replace(r')',r'\)').replace(r';',r'\;')
        byline=self._adb_get('ls -l '+gpath)
        
        if len(byline)>0:
            if byline[0].find('Permission denied')==-1 and byline[0].find('Not a directory')==-1 and byline[0].find('No such file')==-1:
                [on_line(le) for le in byline]
        self.dircache[path] = dirlist
        print('cache',path)
        def is_symlink(info):
            return info['try_retr'] and info['try_cwd'] and 'target' in info

        def resolve_symlink(linkpath):
            linkinfo = self.getinfo(linkpath)
            if 'resolved' not in linkinfo:
                linkinfo['resolved'] = linkpath
            if is_symlink(linkinfo):
                target = linkinfo['target']
                base, fname = pathsplit(linkpath)
                return resolve_symlink(pathjoin(base, target))
            else:
                return linkinfo

        if self.follow_symlinks:
            for name in dirlist:
                if is_symlink(dirlist[name]):
                    target = dirlist[name]['target']
                    linkinfo = resolve_symlink(pathjoin(path, target))
                    for key in linkinfo:
                        if key != 'name':
                            dirlist[name][key] = linkinfo[key]
                    del dirlist[name]['target']
        return dirlist

    @synchronize
    def clear_dircache(self, *paths):
        """
        Clear cached directory information.

        :param path: Path of directory to clear cache for, or all directories if
        None (the default)

        """

        if not paths:
            self.dircache.clear()
        else:
            dircache = self.dircache
            paths = [normpath(abspath(path)) for path in paths]
            for cached_path in list(dircache.keys()):
                for path in paths:
                    if isbase(cached_path, path):
                        dircache.pop(cached_path, None)
                        break

    @synchronize
    def refresh_dircache(self, *paths):
        for path in paths:
            path = abspath(normpath(path))
            self.dircache.pop(path, None)

    @synchronize
    def _check_path(self, path):
        path = normpath(path)
        base, fname = pathsplit(abspath(path))
        dirlist = self._readdir(base)
        if fname and fname not in dirlist:
            raise ResourceNotFoundError(path)
        return dirlist, fname

    def _get_dirlist(self, path):
        path = normpath(path)
        base, fname = pathsplit(abspath(path))
        dirlist = self._readdir(base)
        return dirlist, fname

    
    def __getstate__(self):
        state = super(ADBFS, self).__getstate__()
        del state['_lock']
        state.pop('_adb', None)
        return state

    def __setstate__(self,state):
        super(ADBFS, self).__setstate__(state)
        self._init_dircache()
        self._lock = threading.RLock()
        #self._adb = None
        #self.adb

    def __str__(self):
        return '<ADBFS %s>' % self.host

    def __unicode__(self):
        return '<ADBFS %s>' % self.host

    @convert_os_errors
    def _translate_exception(self, path, exception):

        """ Translates exceptions that my be thrown by the adb code in to
        FS exceptions

        TODO: Flesh this out with more specific exceptions

        """
        raise exception

    @adberrors
    def close(self):
        self.closed = True

    @iotools.filelike_to_stream
    @adberrors
    def open(self, path, mode, buffering=-1, encoding=None, errors=None, newline=None, line_buffering=False, **kwargs):
        path = normpath(path)
        mode = mode.lower()
        print('open'+path+mode)
        if self.isdir(path):
            raise ResourceInvalidError(path)
        if 'r' in mode or 'a' in mode:
            if not self.isfile(path):
                raise ResourceNotFoundError(path)
        if 'w' in mode or 'a' in mode or '+' in mode:
            self.refresh_dircache(dirname(path))
    
        f = _ADBFile(self, normpath(path), mode)
        return f

    @adberrors
    def setcontents(self, path, data=b'', encoding=None, errors=None, chunk_size=1024*64):
        path = normpath(path)
        self.refresh_dircache(dirname(path))
        back=subprocess.Popen('adb shell dd of='+path+' conv=notrunc',shell=True,stdin=subprocess.PIPE)
        back.stdin.write(data)
        back.stdin.write(b'\004')
        back.wait()
        back.kill()
    @adberrors
    def getcontents(self, path, mode="rb", encoding=None, errors=None, newline=None):
        path = normpath(path)
        # 方法1
        back=subprocess.Popen('adb shell dd if='+path+' conv=notrunc',shell=True,stdout=subprocess.PIPE)
        data=back.communicate()[0]
        back.kill()
        if 'b' in mode:
            return data
        return iotools.decode_binary(data, encoding=encoding, errors=errors)
    
    # 方法2 用临时目录 adb pull and open().read()
        
    @adberrors
    def exists(self, path):
        path = normpath(path)
        if path in ('', '/'):
            return True
        dirlist, fname = self._get_dirlist(path)
        return fname in dirlist

    @adberrors
    def isdir(self, path):
       
        path = normpath(path)
        print('isdir '+path)
        if path in ('', '/'):
            return True
        dirlist, fname = self._get_dirlist(path)
        info = dirlist.get(fname)
        if info is None:
            return False
        return info['try_cwd']

    @adberrors
    def isfile(self, path):
        path = normpath(path)
        print('isfile '+path)
        if path in ('', '/'):
            return False
        dirlist, fname = self._get_dirlist(path)
        info = dirlist.get(fname)
        if info is None:
            return False
        return not info['try_cwd']

    @adberrors
    def listdir(self, path="./", wildcard=None, full=False, absolute=False, dirs_only=False, files_only=False):
        path = normpath(path)
        #self.clear_dircache(path)
        if not self.exists(path):
            raise ResourceNotFoundError(path)
        if not self.isdir(path):
            raise ResourceInvalidError(path)
        paths = list(self._readdir(path).keys())

        return self._listdir_helper(path, paths, wildcard, full, absolute, dirs_only, files_only)

    @adberrors
    def listdirinfo(self, path="./",
                          wildcard=None,
                          full=False,
                          absolute=False,
                          dirs_only=False,
                          files_only=False):
        path = normpath(path)
        def getinfo(p):
            try:
                if full or absolute:
                    return self.getinfo(p)
                else:
                    return self.getinfo(pathjoin(path,p))
            except FSError:
                return {}

        return [(p, getinfo(p))
                    for p in self.listdir(path,
                                          wildcard=wildcard,
                                          full=full,
                                          absolute=absolute,
                                          dirs_only=dirs_only,
                                          files_only=files_only)]
    
    @adberrors
    def makedir(self, path, recursive=False, allow_recreate=False):
        path = normpath(path)
        if path in ('', '/'):
            return
        def checkdir(path):
            if not self.isdir(path):
                self.clear_dircache(dirname(path))
                
                stline=self._adb_get('mkdir '+path)
                if recursive or allow_recreate:
                    return
                elif stline[0].find(r"': File exixts")!=-1:
                    raise DestinationExistsError(path, msg="Can not create a directory that already exists : %(path)s")
        if recursive:
            for p in recursepath(path):
                checkdir(p)
        else:
            base = dirname(path)
            if not self.exists(base):
                raise ParentDirectoryMissingError(path)

            if not allow_recreate:
                if self.exists(path):
                    if self.isfile(path):
                        raise ResourceInvalidError(path)
                    raise DestinationExistsError(path)
            checkdir(path)

    @adberrors
    def remove(self, path):
        if not self.exists(path):
            raise ResourceNotFoundError(path)
        if not self.isfile(path):
            raise ResourceInvalidError(path)
        self.refresh_dircache(dirname(path))
        self._adb_get('rm '+path)

    @adberrors
    def removedir(self, path, recursive=False, force=False):
        path = abspath(normpath(path))
        if not self.exists(path):
            raise ResourceNotFoundError(path)
        if self.isfile(path):
            raise ResourceInvalidError(path)
        if normpath(path) in ('', '/'):
            raise RemoveRootError(path)

        if not force:
            for _checkpath in self.listdir(path):
                raise DirectoryNotEmptyError(path)
        try:
            if force:
                for rpath in self.listdir(path, full=True):
                    try:
                        if self.isfile(rpath):
                            self.remove(rpath)
                        elif self.isdir(rpath):
                            self.removedir(rpath, force=force)
                    except FSError:
                        pass
            self.clear_dircache(dirname(path))
            self._adb_get('rmdir '+path)
        except error_reply:
            pass
        if recursive:
            try:
                if dirname(path) not in ('', '/'):
                    self.removedir(dirname(path), recursive=True)
            except DirectoryNotEmptyError:
                pass
        self.clear_dircache(dirname(path), path)

    @adberrors
    def rename(self, src, dst):
        
        self.refresh_dircache(dirname(src), dirname(dst))
        self.adb.rename(_encode(src), _encode(dst))
        st=adb_get('shell mv '+_encode(src)+' '+_encode(dst))
        if st.find('No such')!=-1:
            if st.find(_encode(src))!=-1:
                raise ParentDirectoryMissingError
            elif st.find(_encode(dst))!=-1:
                raise ResourceNotFoundError
        elif st.find('Not a directory')!=-1:
            raise ResourceInvalidError
        
    @adberrors
    def getinfo(self, path):
        dirlist, fname = self._check_path(path)
        if not fname:
            return {}
        info = dirlist[fname].copy()
        info['modified_time'] = datetime.datetime.fromtimestamp(info['mtime'])
        info['created_time'] = info['modified_time']
        return info

    @adberrors
    def getsize(self, path):

        size = None
        if self.dircache.count:
            dirlist, fname = self._check_path(path)
            size = dirlist[fname].get('size')

        if size is not None:
            return size

        st=adb_get('shell stat '+path)
        li=st.splitlines()
        for x in li:
            if x.find('Size:')!=-1:
                li2=x.split()
                size=int(li2[1])
                break
        if size is None:
            dirlist, fname = self._check_path(path)
            size = dirlist[fname].get('size')
        if size is None:
            raise OperationFailedError('getsize', path)
        return size

    @adberrors
    def desc(self, path):
        path = normpath(path)
        
        
        dirlist, fname = self._check_path(path)
        if fname not in dirlist:
            raise ResourceNotFoundError(path)
        return dirlist[fname].get('raw_line', 'No description available')

    @adberrors
    def move(self, src, dst, overwrite=False, chunk_size=16384):
        if not overwrite and self.exists(dst):
            raise DestinationExistsError(dst)
        #self.refresh_dircache(dirname(src), dirname(dst))
        try:
            self.rename(src, dst)
        except:
            self.copy(src, dst, overwrite=overwrite)
            self.remove(src)
        finally:
            self.refresh_dircache(src, dirname(src), dst, dirname(dst))

    @adberrors
    def copy(self, src, dst, overwrite=False, chunk_size=1024*64):
        if not self.isfile(src):
            if self.isdir(src):
                raise ResourceInvalidError(src, msg="Source is not a file: %(path)s")
            raise ResourceNotFoundError(src)
        if not overwrite and self.exists(dst):
            raise DestinationExistsError(dst)

        dst = normpath(dst)
        
        st=adb_get('shell cp -F'+src+' '+dst)
        
        self.refresh_dircache(dirname(dst))
        

    @adberrors
    def movedir(self, src, dst, overwrite=False, ignore_errors=False, chunk_size=16384):
        self.clear_dircache(dirname(src), dirname(dst))
        super(ADBFS, self).movedir(src, dst, overwrite, ignore_errors, chunk_size)

    @adberrors
    def copydir(self, src, dst, overwrite=False, ignore_errors=False, chunk_size=16384):
        self.clear_dircache(dirname(dst))
        super(ADBFS, self).copydir(src, dst, overwrite, ignore_errors, chunk_size)


if __name__ == "__main__":

    pass
