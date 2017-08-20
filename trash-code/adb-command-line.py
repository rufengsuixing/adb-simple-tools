# -*- coding: utf-8 -*-
import os,io
import re,sys
import subprocess
import chardet
def he():
    print('''device work dir
computer work dir
>
dir is for pc list as same as it in cmd
ls is for device simple support ls with no arg
cp or copy [dir1] [dir2]
cd [dir]
link  means reconnect to device
[dir n] means 2 args:the first 'c' means computer ,'d' means device
next arg is the path ,eg: c c:\windows d /sdcard
''')

def d_path_get(s):
    li=re.spilt(':|#',s)
    return li[1]

def main():
    print('寻找设备')
    backstr=adb_out('adb wait-for-device')
    print('找到设备')
    shell=subprocess.Popen(cmd,shell=True,stdout=subprocess.PIPE,stdin=subprocess.PIPE,stderr=subprocess.PIPE)
    tool=subprocess.Popen(cmd,shell=True,stdout=subprocess.PIPE,stdin=subprocess.PIPE,stderr=subprocess.PIPE)
    shell.read().decode('')
    while 1:
        print(dd)
        cd=os.getcwd()
        print(cd)
        print('>',end='')
        command=input()
        #command=input_stream.readline()
        #print(chardet.detect(command))
        print(command)
        '''
        after change the chcp of cmd,input() read error str
        sys.stdin.encoding=cp936
        '''
        li=command.split()
        if li[0]=='ls':
            if len(li)==1:
                backstr=adb_out('adb shell ls '+dd)
            else:
                li[1]=path_get(li[1],dd)
                backstr=adb_out('adb shell ls '+li[1])
            
            '''
            if len(li)==1:
                back=os.popen('adb shell ls '+dd)
            else:
                back=os.popen('adb shell ls '+li[1])
            
            there is a problem ,
            the default decode is back.__dict__['_stream'].encoding='cp936'
            and i can`t change it,maybe i should use ctype to make a monkey patch
            '''
            li=backstr.split()
            for a in li:
                print(a,end='  ')
            print('')
            continue
        elif li[0]=='dir':
            back=subprocess.Popen(command,shell=True,stdout=subprocess.PIPE)
            backstr=back.stdout.read().decode('cp936')
        elif li[0]=='cp' or li[0]=='copy':
            if len(li)!=5:
                print('not enough args,see help for more info')
                continue
            if (not li[1]=='c' and not li[1]=='d') or (not li[3]=='c' and not li[3]=='d'):
                print('error args,see help for more info')
                continue
            if li[1]=='d':
                li[2]=path_get(li[2],dd)
            if li[3]=='d':
                li[4]=path_get(li[4],dd)
            if li[1]=='c' and li[3]=='d':
                backstr=adb_out('adb push '+li[2]+' '+li[4])
            elif li[1]=='d' and li[3]=='c':
                backstr=adb_out('adb pull '+li[2]+' '+li[4])
            elif li[1]=='d' and li[3]=='d':
                backstr=adb_out('adb shell cp -r '+li[2]+' '+li[4])
            elif li[1]=='c' and li[3]=='c':
                backstr=adb_out('copy '+li[2]+' '+li[4])
        elif li[0]=='cd':
            if len(li)!=3:
               print('not enough args,see help for more info')
               continue
            if li[1]=='d':
                li[2]=path_get(li[2],dd)
                backstr=adb_out('adb shell cd '+li[2])
                if not re.search('No.*',backstr):
                    dd=li[2]
                
                #if backstr:
                #    with open(r'C:\Users\yuan\Desktop\新建文件夹\log.txt','w',encoding='utf-16',errors='ignore') as log:
                #        log.write(backstr)
                print(backstr)
                
                continue
            elif li[1]=='c':
                try:
                    os.chdir(' '.join(li[2:]))
                except Exception as e:
                    print(e)
                continue
            else:
                print('error args,see help for more info')
                continue
        elif li[0]=='link':
            print('重新连接')
            backstr=adb_out('adb wait-for-device')
        elif li[0]=='help':
            he()
            continue
        elif li[0]=='exit':
            exit(1)
        else:
            print('unknown command')
        if re.search('error: device .* not found',backstr):
            print('断开了，重新连接')
            backstr=adb_out('adb wait-for-device')
        print(backstr)

    
if __name__=='__main__':
    main()