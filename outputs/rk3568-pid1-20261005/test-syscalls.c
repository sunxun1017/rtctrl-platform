/* SPDX-License-Identifier: MIT. External syscall model for real pid1.c main. */
#define _GNU_SOURCE
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <setjmp.h>
#include <signal.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/mount.h>
#include <sys/stat.h>
#include <sys/statfs.h>
#include <sys/syscall.h>
#include <sys/sysmacros.h>
#include <sys/types.h>
#include <sys/utsname.h>
#include <sys/wait.h>
#include <unistd.h>
#include <linux/fs.h>
#include <linux/loop.h>
extern int pid1_main(int, char **);
extern int __real_open(const char *, int, ...);
extern int __real_fstat(int, struct stat *);
extern int __real_close(int);
extern ssize_t __real_read(int, void *, size_t);
extern int __real_mkdir(const char *, mode_t);
extern int __real_symlink(const char *, const char *);
extern DIR *__real_opendir(const char *);
extern int __real_closedir(DIR *);
extern struct dirent *__real_readdir(DIR *);
extern pid_t __real_waitpid(pid_t,int *,int);
static jmp_buf done;
static char fixture[512], scenario[128], mode[32];
static char fdpaths[2048][512];
static int calls, injection, failed, bound=1, input_sent, moved_root, pivoted;
static unsigned char read_seen[2048],write_seen[2048];
static int fake_child, commands_position, pipe_count, child_branch;
static int stdflags[3];
static struct { char path[256],type[32]; unsigned id,parent,major,minor;int ro; } mounts[32];
static size_t mount_count;
static dev_t executable_dev;
static int postpivot_extra;
static DIR *fd_directory, *proc_directory;
static int extra_returned;
static int event(const char *name)
{
    calls++;
    fprintf(stderr,"CALL %d %s\n",calls,name);
    if(injection==calls&&!failed) {
        failed=1;
        if(!strcmp(scenario,"exec-resume")) input_sent=0;
        errno=EIO;fprintf(stderr,"INJECTED %s\n",name);return -1;
    }
    return 0;
}
static int is(const char *name) { return !strcmp(name,scenario); }
static int suffix(const char *s,const char *tail)
{
    size_t a=strlen(s),b=strlen(tail);return a>=b&&!strcmp(s+a-b,tail);
}
static void add_mount(const char *path,const char *type,unsigned major,unsigned minor,int ro)
{
    unsigned id=100+(unsigned)mount_count,parent=10;
    if(!strcmp(path,"/")&&!strcmp(type,"rootfs")) id=10;
    else if((!strcmp(path,"/")&&!strcmp(type,"ext4"))||!strcmp(path,"/newroot")) id=11;
    else if(strstr(path,"ram-return")) { id=12;parent=11; }
    else if(strstr(path,"backing-cache")) id=13;
    else if(!strcmp(path,"/dev")) id=14;
    else if(!strcmp(path,"/dev/pts")) { id=15;parent=14; }
    else if(!strcmp(path,"/proc")) id=16;
    else if(!strcmp(path,"/sys")) id=17;
    else if(!strcmp(path,"/tmp")) id=18;
    else if(!strcmp(path,"/run")) id=19;
    if(strcmp(mode,"bootstrap")&&id>=13&&id!=15) parent=11;
    if(id==10) parent=1;
    snprintf(mounts[mount_count].path,256,"%s",path);
    snprintf(mounts[mount_count].type,32,"%s",type);
    mounts[mount_count].id=id;mounts[mount_count].parent=parent;
    mounts[mount_count].major=major;mounts[mount_count].minor=minor;mounts[mount_count].ro=ro;mount_count++;
}
static int fixture_open(const char *name,int flags, mode_t permissions)
{
    char p[1024];snprintf(p,sizeof(p),"%s/%s",fixture,name);
    return __real_open(p,flags,permissions);
}
static int generated(const char *text)
{
    extern ssize_t __real_write(int,const void *,size_t);
    extern off_t __real_lseek(int,off_t,int);
    static unsigned serial;
    char name[64];snprintf(name,sizeof(name),"generated-%u",serial++);
    int fd=fixture_open(name,O_RDWR|O_CREAT|O_TRUNC,0600);
    if(fd<0) abort();
    if(__real_write(fd,text,strlen(text))!=(ssize_t)strlen(text)) abort();
    __real_lseek(fd,0,SEEK_SET);return fd;
}
static int mountinfo(void)
{
    char result[16384]={0};size_t used=0;
    for(size_t i=0;i<mount_count;i++) {
        unsigned id=mounts[i].id,parent=mounts[i].parent;
        if(is("wrong-mount-id")&&id==15) id=55;
        if(is("wrong-mount-parent")&&id==15) parent=11;
        unsigned ma=mounts[i].major,mi=mounts[i].minor;
        if(is("wrong-mount-device")&&id==15) mi=77;
        const char *type=mounts[i].type;
        if(is("wrong-mount-fs")&&id==15) type="tmpfs";
        int n=snprintf(result+used,sizeof(result)-used,"%u %u %u:%u / %s %s - %s /dev/model %s\n",id,parent,ma,mi,mounts[i].path,mounts[i].ro?"ro,nosuid,nodev":"rw,nosuid",type,mounts[i].ro?"ro,noload":"rw");
        if(n<0||(size_t)n>=sizeof(result)-used) abort();used+=(size_t)n;
    }
    if(is("extra-mount")) strcat(result,"99 10 0:9 / /unknown rw - tmpfs tmpfs rw\n");
    if(is("duplicate-devpts")) strcat(result,"99 14 0:9 / /dev/pts rw - devpts devpts rw\n");
    if(postpivot_extra) strcat(result,"99 12 0:9 / /unknown rw - tmpfs tmpfs rw\n");
    return generated(result);
}
pid_t __wrap_getpid(void) { return is("not-pid1")?42:1; }
uid_t __wrap_getuid(void) { return is("not-root")?1000:0; }
int __wrap_open(const char *path,int flags,...)
{
    mode_t permissions=0;
    if(flags&O_CREAT) { va_list ap;va_start(ap,flags);permissions=(mode_t)va_arg(ap,int);va_end(ap); }
    char label[600];snprintf(label,sizeof(label),"open %s flags=%d",path,flags);
    if(event(label)<0) return -1;
    int fd=-1;
    if(suffix(path,"/console")||suffix(path,"/loop-control")||suffix(path,"/loop2")||suffix(path,"/mmcblk0p12")) fd=fixture_open("dummy",O_RDWR,0);
    else if(suffix(path,"/uevent")) fd=generated(is("bad-cache-partname")?"MAJOR=179\nPARTNAME=system\n":"MAJOR=179\nPARTNAME=cache\n");
    else if(suffix(path,"/size")) fd=generated(is("bad-cache-size")?"786430\n":"786432\n");
    else if(suffix(path,"/dev")&&strstr(path,"mmcblk0p12")) fd=generated(is("bad-cache-major")?"8:12\n":"179:12\n");
    else if(suffix(path,"/manifest")) fd=fixture_open("manifest",O_RDONLY,0);
    else if(suffix(path,"/state")) fd=fixture_open("state",flags&~(O_NOFOLLOW|O_EXCL),permissions);
    else if(suffix(path,"/mountinfo")) fd=mountinfo();
    else if(suffix(path,"/stat")&&strstr(path,"/123/")) fd=generated(is("session-mismatch")?"123 (surviving process) S 1 123 124 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 20 0 0 0\n":"123 (surviving process) S 1 123 123 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 20 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0\n");
    else if(suffix(path,"/rtctrl-rcu-reset-20261004/Image")) fd=__real_open("/home/sx/projects/rtctrl-platform/outputs/rk3568-rcu-reset-20261004/Image",O_RDONLY);
    else if(suffix(path,"/rootfs-pid1.ext4")) {
        if(strcmp(path,"/backing-cache/rtctrl-pid1-20261005-v3/rootfs-pid1.ext4")) abort();
        fd=fixture_open("rootfs",O_RDONLY,0);
    }
    else if(suffix(path,"/busybox")) {
        if(flags&O_CREAT) fd=fixture_open("island-bin/busybox",flags&~O_NOFOLLOW,permissions);
        else if(strstr(path,"ram-return")) fd=fixture_open("island-bin/busybox",O_RDONLY,0);
        else fd=__real_open("/home/sx/projects/rtctrl-platform/outputs/rk3568-rng-network-20261004/build/busybox-module-options/v1/busybox",O_RDONLY);
        if(is("bad-busybox-sha")&&!(flags&O_CREAT)) { if(fd>=0) __real_close(fd);fd=fixture_open("abc",O_RDONLY,0); }
    } else if(suffix(path,"/codec-test")) fd=__real_open("/home/sx/projects/rtctrl-platform/outputs/rk3568-mcu-baseline-20261003/private/source-tests/rtctrl_patchx_codec_test",O_RDONLY);
    else if(suffix(path,"/pty-test")) fd=__real_open("/home/sx/projects/rtctrl-platform/outputs/rk3568-mcu-baseline-20261003/private/source-tests/rtctrl_patchx_pty_test",O_RDONLY);
    else if(!strcmp(path,"/init")||suffix(path,"/pid1")||suffix(path,"/exe")) {
        const char *name=(flags&O_CREAT)?"island-pid1":"abc";
        if(is("bad-pid1-sha")&&!(flags&O_CREAT)) name="bad";
        fd=fixture_open(name,flags&~O_NOFOLLOW,permissions);
    }
    if(fd<0) { errno=ENOENT;return -1; }
    if(suffix(path,"/console")&&is("cloexec-console")) { __real_close(fd);fd=0;stdflags[0]=FD_CLOEXEC; }
    if(fd>=2048) abort();snprintf(fdpaths[fd],512,"%s",path);read_seen[fd]=write_seen[fd]=0;
    return fd;
}
int __wrap___open_2(const char *path,int flags) { return __wrap_open(path,flags); }
int __wrap_fstat(int fd,struct stat *sb)
{
    if(event("fstat")<0) return -1;
    if(fd<=2) { memset(sb,0,sizeof(*sb));sb->st_mode=S_IFCHR|0600;sb->st_rdev=makedev(5,1);return 0; }
    if(__real_fstat(fd,sb)<0) return -1;
    sb->st_uid=0;sb->st_gid=0;
    if(is("file-uid")) sb->st_uid=1000;
    const char *p=fdpaths[fd];
    if(suffix(p,"/console")) { sb->st_mode=S_IFCHR|0600;sb->st_rdev=makedev(5,1); }
    if(suffix(p,"/mmcblk0p12")) { sb->st_mode=S_IFBLK|0600;sb->st_rdev=makedev(is("bad-cache-fstat")?8:179,12); }
    if(suffix(p,"/loop-control")) { sb->st_mode=S_IFCHR|0600;sb->st_rdev=makedev(10,237); }
    if(suffix(p,"/loop2")) { sb->st_mode=S_IFBLK|0600;sb->st_rdev=makedev(is("bad-loop-device")?8:7,2); }
    if(suffix(p,"/rootfs-pid1.ext4")) { sb->st_dev=makedev(179,12);sb->st_ino=42; }
    if(suffix(p,"/state")) sb->st_dev=makedev(0,4);
    if(suffix(p,"/exe")) sb->st_dev=is("wrong-exe-device")?makedev(8,9):executable_dev;
    return 0;
}
int __wrap_stat(const char *path,struct stat *sb)
{
    char label[512];snprintf(label,sizeof(label),"stat %s",path);
    if(event(label)<0) return -1;
    memset(sb,0,sizeof(*sb));sb->st_mode=S_IFDIR|0755;
    sb->st_dev=strstr(path,"ram-return")?makedev(0,4):makedev(is("bad-root-device")?8:7,2);
    for(size_t i=0;i<mount_count;i++) if(!strcmp(mounts[i].path,path)) sb->st_dev=makedev(mounts[i].major,mounts[i].minor);
    if(is("bad-root-device")&&!strcmp(path,"/")) sb->st_dev=makedev(8,2);
    return 0;
}
int __wrap_statfs(const char *path,struct statfs *sb)
{
    char label[512];snprintf(label,sizeof(label),"statfs %s",path);
    if(event(label)<0) return -1;
    memset(sb,0,sizeof(*sb));sb->f_type=(strstr(path,"ram-return")||pivoted)?0x01021994:0xef53;
    if(is("bad-island-fs")&&strstr(path,"ram-return")) sb->f_type=0xef53;
    return 0;
}
ssize_t __wrap_read(int fd,void *buf,size_t n)
{
    if(fd==0) {
        const char *commands=getenv("CONSOLE_COMMANDS");
        if(commands&&commands[commands_position]) {
            size_t k=strlen(commands+commands_position);if(k>n) k=n;
            memcpy(buf,commands+commands_position,k);commands_position+=(int)k;return (ssize_t)k;
        }
        if((is("resume")||is("exec-resume")||is("postpivot-extra"))&&failed&&!input_sent) {
            const char *cmd="resume\n";static size_t position;
            size_t k=strlen(cmd)-position;if(k>n) k=n;
            memcpy(buf,cmd+position,k);position+=k;
            if(position==strlen(cmd)) input_sent=1;
            return (ssize_t)k;
        }
        if(!input_sent&&!failed&&(!commands||!*commands)&&!strcmp(mode,"root")&&!is("no-return")) {
            const char *cmd="return\n";
            static size_t position;
            size_t k=strlen(cmd)-position;if(k>n) k=n;
            memcpy(buf,cmd+position,k);position+=k;
            if(position==strlen(cmd)) input_sent=1;
            return (ssize_t)k;
        }
        puts("OBSERVED_PID1_ALIVE");longjmp(done,1);
    }
    if(!strcmp(fdpaths[fd],"pipe-read")||!strcmp(fdpaths[fd],"permit-read")) {
        if(event("read session pipe")<0) return -1;
        if(n) { *(char *)buf=!strcmp(fdpaths[fd],"pipe-read")?'R':'C';return 1; }return 0;
    }
    /* Fault injection is per operation, not per bulk hash read. */
    if(!read_seen[fd]) {
        read_seen[fd]=1;char label[600];snprintf(label,sizeof(label),"read %s",fdpaths[fd]);
        if(event(label)<0) return -1;
    }
    if(is("read-error")) { errno=EIO;return -1; }
    return __real_read(fd,buf,n);
}
ssize_t __wrap_write(int fd,const void *buf,size_t n)
{
    extern ssize_t __real_write(int,const void *,size_t);
    if(fd<=2) return __real_write(fd,buf,n);
    if(!write_seen[fd]) {
        write_seen[fd]=1;char label[600];snprintf(label,sizeof(label),"write %s",fdpaths[fd]);
        if(event(label)<0) return -1;
    }
    return __real_write(fd,buf,n);
}
off_t __wrap_lseek(int fd,off_t offset,int whence)
{
    extern off_t __real_lseek(int,off_t,int);
    char label[600];snprintf(label,sizeof(label),"lseek %s offset=%lld",fdpaths[fd],(long long)offset);
    if(event(label)<0) return -1;
    read_seen[fd]=0;
    return __real_lseek(fd,offset,whence);
}
int __wrap_close(int fd)
{
    if(event("close")<0) { __real_close(fd);return -1; }
    if(fd>2) fdpaths[fd][0]=0;
    return __real_close(fd);
}
int __wrap_fcntl(int fd,int command,...)
{
    if(event("fcntl")<0) return -1;
    if(command==F_GETFD&&fd<=2) return stdflags[fd];
    if(command==F_SETFD&&fd<=2) { va_list ap;va_start(ap,command);stdflags[fd]=va_arg(ap,int);va_end(ap); }
    return 0;
}
int __wrap_dup2(int oldfd,int newfd) { if(event("dup2")<0) return -1;if(oldfd!=newfd) stdflags[newfd]=0;return newfd; }
int __wrap_sigaction(int sig,const struct sigaction *a,struct sigaction *b)
{
    (void)sig;(void)a;(void)b;return event("sigaction");
}
int __wrap_uname(struct utsname *u)
{
    if(event("uname")<0) return -1;
    memset(u,0,sizeof(*u));strcpy(u->release,"5.10.160-rt89-g9f9e9d18574d-dirty");strcpy(u->machine,"aarch64");
    if(is("bad-release")) strcpy(u->release,"4.19-Android");return 0;
}
int __wrap_mount(const char *s,const char *t,const char *fs,unsigned long flags,const void *data)
{
    char label[1024];snprintf(label,sizeof(label),"mount %s %s %s flags=%lu data=%s",s?s:"-",t,fs?fs:"-",flags,data?(const char *)data:"-");
    if(event(label)<0) return -1;
    if(flags==MS_MOVE) {
        if(s&&!strcmp(s,".")) {
            moved_root=1;
            for(size_t i=0;i<mount_count;i++) {
                if(!strcmp(mounts[i].path,"/")) { mounts[i]=mounts[--mount_count];i--;continue; }
                if(!strncmp(mounts[i].path,"/newroot",8)) {
                    char path[256];snprintf(path,sizeof(path),"%s",mounts[i].path+8);
                    strcpy(mounts[i].path,*path?path:"/");
                }
            }
        } else {
            size_t n=strlen(s);
            unsigned parent=(!strncmp(t,"/.ram-return/",13))?12:11;
            for(size_t i=0;i<mount_count;i++) if(!strcmp(mounts[i].path,s)||(!strncmp(mounts[i].path,s,n)&&mounts[i].path[n]=='/')) {
                char path[512];snprintf(path,sizeof(path),"%s%s",t,mounts[i].path+n);
                if(!strcmp(mounts[i].path,s)) mounts[i].parent=parent;
                if(strlen(path)>=256) abort();strcpy(mounts[i].path,path);
            }
        }
    } else if(fs) {
        unsigned ma=0,mi=(unsigned)mount_count+1;
        if(!strcmp(t,"/dev")) mi=2;
        else if(!strcmp(t,"/dev/pts")) mi=3;
        else if(!strcmp(t,"/proc")) mi=5;
        else if(!strcmp(t,"/sys")) mi=6;
        else if(!strcmp(t,"/tmp")) mi=7;
        else if(!strcmp(t,"/run")) mi=8;
        else if(strstr(t,"ram-return")) mi=4;
        if(!strcmp(fs,"ext4")) { ma=strstr(s,"loop")?7:179;mi=ma==7?2:12; }
        add_mount(t,fs,ma,mi,(flags&MS_RDONLY)!=0);
    }
    return 0;
}
int __wrap_mkdir(const char *path,mode_t permissions)
{
    (void)permissions;char label[512];snprintf(label,sizeof(label),"mkdir %s",path);return event(label);
}
int __wrap_unlink(const char *path) { (void)path;return event("unlink ptmx"); }
int __wrap_symlink(const char *target,const char *link)
{
    if(!strcmp(target,"pts/ptmx")&&!strcmp(link,"/dev/ptmx")) return event("symlink ptmx");
    static const char prefix[]="/newroot/.ram-return/bin/";
    if(strcmp(target,"busybox")||strncmp(link,prefix,sizeof(prefix)-1)||!link[sizeof(prefix)-1]||
       strchr(link+sizeof(prefix)-1,'/')) abort();
    char label[512],path[1024];
    snprintf(label,sizeof(label),"symlink %s %s",target,link);
    if(event(label)<0) return -1;
    snprintf(path,sizeof(path),"%s/island-bin/%s",fixture,link+sizeof(prefix)-1);
    return __real_symlink(target,path);
}
int __wrap_fsync(int fd) { (void)fd;return event("fsync"); }
int __wrap_chdir(const char *path)
{
    char label[512];snprintf(label,sizeof(label),"chdir %s",path);return event(label);
}
int __wrap_chroot(const char *path)
{
    char label[512];snprintf(label,sizeof(label),"chroot %s",path);return event(label);
}
long __wrap_syscall(long number,...)
{
    va_list ap;va_start(ap,number);const char *root=va_arg(ap,const char *),*old=va_arg(ap,const char *);va_end(ap);
    if(number!=SYS_pivot_root) abort();
    char label[512];snprintf(label,sizeof(label),"pivot_root %s %s",root,old);
    if(event(label)<0) return -1;
    pivoted=1;
    for(size_t i=0;i<mount_count;i++) {
        if(!strcmp(mounts[i].path,"/")) { strcpy(mounts[i].path,"/old-root");mounts[i].parent=12; }
        else if(!strncmp(mounts[i].path,"/.ram-return",12)) {
            char path[256];snprintf(path,sizeof(path),"%s",mounts[i].path+12);
            strcpy(mounts[i].path,*path?path:"/");
            if(!*path) mounts[i].parent=10;
        }
    }
    return 0;
}
int __wrap_umount2(const char *path,int flags)
{
    char label[512];snprintf(label,sizeof(label),"umount %s flags=%d",path,flags);
    if(event(label)<0) { if(is("postpivot-extra")&&pivoted) postpivot_extra=1;return -1; }
    if(flags||(!strcmp(path,"/backing-cache")&&bound)) abort();
    if(!strcmp(path,"/old-root")&&executable_dev==makedev(7,2)) {
        fprintf(stderr,"MODEL_EXECUTABLE_BUSY /old-root\n");errno=EBUSY;return -1;
    }
    for(size_t i=0;i<mount_count;i++) if(!strcmp(mounts[i].path,path)) { mounts[i]=mounts[--mount_count];return 0; }
    errno=EINVAL;return -1;
}
int __wrap_ioctl(int fd,unsigned long request,...)
{
    va_list ap;va_start(ap,request);void *argument=NULL;
    if(request!=LOOP_CTL_GET_FREE&&request!=LOOP_CLR_FD) argument=va_arg(ap,void *);
    va_end(ap);
    char label[256];snprintf(label,sizeof(label),"ioctl 0x%lx",request);
    if(event(label)<0) return -1;
    (void)fd;
    if(request==BLKGETSIZE64) { *(uint64_t *)argument=is("bad-cache-bytes")?100:384ULL*1024*1024;return 0; }
    if(request==LOOP_CTL_GET_FREE) return 2;
    if(request==LOOP_SET_FD) { if(bound) abort();bound=1;return 0; }
    if(request==LOOP_SET_STATUS64) { struct loop_info64 *li=argument;if(li->lo_flags!=1) abort();return 0; }
    if(request==LOOP_CLR_FD) {
        for(size_t i=0;i<mount_count;i++) if(mounts[i].major==7) abort();
        bound=0;return 0;
    }
    if(request==LOOP_GET_STATUS64) {
        if(!bound) { errno=ENXIO;return -1; }
        struct loop_info64 *li=argument;memset(li,0,sizeof(*li));
        li->lo_device=makedev(179,12);li->lo_inode=42;li->lo_number=2;li->lo_flags=is("bad-loop-flags")?5:1;
        if(is("bad-loop-inode")) li->lo_inode=99;
        if(is("bad-loop-rdevice")) li->lo_rdevice=makedev(8,1);
        if(is("bad-loop-encryption")) li->lo_encrypt_type=1;
        return 0;
    }
    if(request==TIOCSCTTY) return 0;
    abort();
}
DIR *__wrap_opendir(const char *path)
{
    char label[512];snprintf(label,sizeof(label),"opendir %s",path);
    if(event(label)<0) return NULL;
    char real[1024];snprintf(real,sizeof(real),"%s/empty",fixture);
    DIR *d=__real_opendir(real);
    if(suffix(path,"/fd")) { fd_directory=d;extra_returned=0; }
    else { proc_directory=d;extra_returned=0; }
    return d;
}
struct dirent *__wrap_readdir(DIR *d)
{
    static struct dirent entry;
    if(!extra_returned&&((d==fd_directory&&is("extra-fd"))||(d==proc_directory&&is("unknown-user")))) {
        extra_returned=1;memset(&entry,0,sizeof(entry));strcpy(entry.d_name,d==fd_directory?"88":"123");return &entry;
    }
    return __real_readdir(d);
}
int __wrap_closedir(DIR *d)
{
    if(d==fd_directory) fd_directory=NULL;
    if(d==proc_directory) proc_directory=NULL;
    if(event("closedir")<0) { __real_closedir(d);return -1; }
    return __real_closedir(d);
}
pid_t __wrap_waitpid(pid_t pid,int *status,int options)
{
    (void)pid;(void)status;(void)options;
    if(event("waitpid")<0) return -1;
    if(fake_child&&(pid==-1||pid==123)) { if(status) *status=is("child-nonzero")?7<<8:(is("child-signal")?9:0);fake_child=0;return 123; }
    errno=ECHILD;return -1;
}
pid_t __wrap_fork(void)
{
    if(event("fork")<0) return -1;
    if(is("child-branch")) { child_branch=1;return 0; }
    fake_child=1;return 123;
}
int __wrap_pipe2(int descriptors[2],int flags)
{
    (void)flags;
    if(event("pipe2")<0) return -1;
    descriptors[0]=fixture_open("dummy",O_RDONLY,0);descriptors[1]=fixture_open("dummy",O_WRONLY,0);
    strcpy(fdpaths[descriptors[0]],pipe_count?"permit-read":"pipe-read");strcpy(fdpaths[descriptors[1]],pipe_count?"permit-write":"pipe-write");
    read_seen[descriptors[0]]=write_seen[descriptors[1]]=0;pipe_count++;return 0;
}
int __wrap_poll(struct pollfd *descriptors,nfds_t count,int timeout)
{
    (void)timeout;
    if(event("poll")<0) return -1;
    if(count) descriptors[0].revents=POLLIN;return 1;
}
pid_t __wrap_setsid(void) { return event("setsid")<0?-1:123; }
int __wrap_kill(pid_t pid,int sig)
{
    char label[128];snprintf(label,sizeof(label),"kill pid=%ld signal=%d",(long)pid,sig);
    if(pid!=-123) abort();return event(label);
}
void __wrap__exit(int status)
{
    extern void __real__exit(int);
    if(!child_branch) __real__exit(status);
    printf("OBSERVED_CHILD_EXIT %d\n",status);longjmp(done,1);
}
int __wrap_execve(const char *path,char *const args[],char *const env[])
{
    (void)env;char label[512];snprintf(label,sizeof(label),"execve %s %s",path,args[1]?args[1]:"-");
    if(event(label)<0) return -1;
    if(stdflags[0]||stdflags[1]||stdflags[2]) { errno=EBADF;return -1; }
    fprintf(stdout,"OBSERVED_EXEC %s %s\n",path,args[1]?args[1]:"-");
    if(is("exec-resume")&&!strcmp(path,"/.ram-return/bin/pid1")) {
        extern ssize_t __real_write(int,const void *,size_t);
        extern int __real_execve(const char *,char *const [],char *const []);
        executable_dev=makedev(0,4);
        int fd=fixture_open("model-transfer",O_WRONLY|O_CREAT|O_TRUNC,0600);
        if(fd<0) abort();
        if(__real_write(fd,mounts,sizeof(mounts))!=(ssize_t)sizeof(mounts)||
           __real_write(fd,&mount_count,sizeof(mount_count))!=(ssize_t)sizeof(mount_count)||
           __real_write(fd,&calls,sizeof(calls))!=(ssize_t)sizeof(calls)) abort();
        __real_close(fd);fflush(stdout);
        setenv("MODEL_TRANSFER","1",1);
        const char *binary=getenv("SELF_BINARY"),*launcher=getenv("SELF_LAUNCHER");
        char *next[]={ (char *)binary, "return", NULL };
        char *cross[]={ (char *)launcher,(char *)binary,"return",NULL };
        extern char **environ;
        __real_execve(launcher&&*launcher?launcher:binary,launcher&&*launcher?cross:next,environ);
        perror("model exec");abort();
    }
    longjmp(done,1);
}
int main(int argc,char **argv)
{
    const char *path=getenv("FIXTURE");if(!path) abort();snprintf(fixture,sizeof(fixture),"%s",path);
    snprintf(scenario,sizeof(scenario),"%s",getenv("SCENARIO")?getenv("SCENARIO"):"ok");
    injection=getenv("FAIL_AT")?atoi(getenv("FAIL_AT")):0;
    snprintf(mode,sizeof(mode),"%s",argc>1?argv[1]:"bootstrap");
    executable_dev=!strcmp(mode,"root")?makedev(7,2):(!strcmp(mode,"bootstrap")?makedev(0,1):makedev(0,4));
    if(!strcmp(mode,"bootstrap")) { bound=is("loop-inuse");add_mount("/","rootfs",0,1,0); }
    else {
        add_mount("/","ext4",7,2,1);add_mount("/.ram-return","tmpfs",0,4,0);
        add_mount("/.backing-cache","ext4",179,12,1);add_mount("/dev","devtmpfs",0,2,0);
        add_mount("/dev/pts","devpts",0,3,0);add_mount("/proc","proc",0,5,0);
        add_mount("/sys","sysfs",0,6,0);add_mount("/tmp","tmpfs",0,7,0);add_mount("/run","tmpfs",0,8,0);
    }
    if(getenv("MODEL_TRANSFER")) {
        int fd=fixture_open("model-transfer",O_RDONLY,0);
        if(fd<0||__real_read(fd,mounts,sizeof(mounts))!=(ssize_t)sizeof(mounts)||
           __real_read(fd,&mount_count,sizeof(mount_count))!=(ssize_t)sizeof(mount_count)||
           __real_read(fd,&calls,sizeof(calls))!=(ssize_t)sizeof(calls)) abort();
        __real_close(fd);failed=1;input_sent=1;executable_dev=makedev(0,4);
    }
    if(!setjmp(done)) { int rc=pid1_main(argc,argv);printf("OBSERVED_MAIN_RETURN %d\n",rc); }
    fprintf(stderr,"MODEL_FINAL calls=%d injected=%d bound=%d moved_root=%d pivoted=%d\n",calls,failed,bound,moved_root,pivoted);
    child_branch=0;
    return 0;
}
