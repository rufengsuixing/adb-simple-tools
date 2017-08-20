
import os
import subprocess
from fs.errors import *
from fs.base import *
import fs
import datetime
def adb_get(command):
    #debug
    #print(command)
    back=subprocess.Popen('adb '+command,shell=True,stdout=subprocess.PIPE)
    str=back.communicate()
    back.kill()
    #DEBUG
    #print (str[0].decode('utf-8'))
    return str[0].decode('utf-8')
class adb(FS):
    
    _meta = {'thread_safe': False,
             'network': True,
             'virtual': False,
             'read_only': False,
             'unicode_paths': True,
             'case_insensitive_paths': False,
             'atomic.move': False,
             'atomic.copy': False,
             'atomic.makedir': True,
             'atomic.rename': True,
             'atomic.setcontents': False}
    
    def __init__(self):
        adb_get('wait_for_device')
        self.path=''
    def cache_hint(self,enabled):
        return True
    def open(self, path, mode='r', buffering=-1, encoding=None, errors=None, newline=None, line_buffering=False, **kwargs):
        os.makedirs('')
        path=fs.path.normpath(fs.path.adspath(path))
        path2=fs.path.pathsplit(path)
        pathwd=path2[0]
        os.makedirs('C:/Documents and Settings/User/Local Settings/Temp/adb_tmp'+pathwd, exist_ok=True)
        st=adb_get('pull '+path+r' C:/Documents and Settings/User/Local Settings/Temp/adb_tmp'+path)
        self.path=path
        self.op=open('C:/Documents and Settings/User/Local Settings/Temp/adb_tmp'+path, mode, buffering, encoding, errors, newline, line_buffering, **kwargs)
        return self.op
    def close(self):
        path=self.path
        st=adb_get('push '+path+' '+'C:/Documents and Settings/User/Local Settings/Temp/adb_tmp'+path)
        self.op.close()
    def isfile(self,path):
        print('isfile'+path)
        st=adb_get('shell if [ -f '+path+' ]; then echo 6; else echo 9; fi\n')
        if st=='6\r\r\n':
            return True
        else:
            return False
    def isdir(self,path):
        print('isdir'+path)
        st=adb_get('shell if [ -d '+path+' ]; then echo 6; else echo 9; fi\n')
        if st=='6\r\r\n':
            return True
        else:
            return False
    def listdir(self,path,wildcard=None, full=False, absolute=False, dirs_only=False, files_only=False):
        print('listdir'+path)
        path=fs.path.forcedir(path)
        if wildcard!=None:
            st=adb_get('shell ls '+path+' | grep '+wildcard)
        else:
            st=adb_get('shell ls '+path)
        li=st.split()
        print([ path+a for a in li if a])
        return [ path+a for a in li if a]
        
    def makedir(self,path):
        st=adb_get('shell mkdir '+path)
        if st.find(r"': File exixts")!=-1:
            raise DestinationExistsError(path, msg="Can not create a directory that already exists : %(path)s")
        else:
            return None
    def remove(self,path):
        st=adb_get('shell rm '+path)
        if st.find(r"Is a directory")!=-1:
            raise UnsupportedError("remove file", msg="Can only remove file")
        elif st.find(r"No such file")!=-1:
            raise ResourceNotFoundError(path)
        else:    
            return None
    def removedir(self,path):
        st=adb_get('shell rmdir '+path)
        return None
    def rename(self,s,d):
        st=adb_get('shell mv '+s+' '+d)
        
    def getinfo(self,path):
        ret={}
        flag=0
        st=adb_get('shell stat '+path)
        li=st.splitlines()
        for x in li:
            if x.find('Size:')!=-1:
                li2=x.split()
                ret['size']=int(li2[1])
            elif x.find('Access:')!=-1:
                if flag==0:
                    flag=1
                    continue
                else:
                    flag=0
                li2=x.split()
                li3=li2[2].split('.')
                ret['accessed_time']=datetime.datetime.strptime(li2[1]+' '+li3[0],'%Y-%m-%d %H:%M:%S')
            elif x.find('Modify:')!=-1:
                li2=x.split()
                li3=li2[2].split('.')
                ret['modified_time']=datetime.datetime.strptime(li2[1]+' '+li3[0],'%Y-%m-%d %H:%M:%S')
            elif x.find('Change')!=-1:
                li2=x.split()
                li3=li2[2].split('.')
                ret['created_time']=datetime.datetime.strptime(li2[1]+' '+li3[0],'%Y-%m-%d %H:%M:%S')
        print(ret)
        return ret
        
    
        