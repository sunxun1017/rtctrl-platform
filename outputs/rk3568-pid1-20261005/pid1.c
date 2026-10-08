/* SPDX-License-Identifier: MIT
 * Copyright (c) 2026 rtctrl-platform contributors.
 * Native PID1 only. The production file contains no test hooks.
 */
#define _GNU_SOURCE
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <signal.h>
#include <stdint.h>
#include <stddef.h>
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
#include <linux/fs.h>
#include <linux/loop.h>
#include <termios.h>
#include <unistd.h>

_Static_assert(sizeof(struct loop_info64) == 232, "locked loop_info64 size");
_Static_assert(offsetof(struct loop_info64,lo_inode)==8 && offsetof(struct loop_info64,lo_rdevice)==16 && offsetof(struct loop_info64,lo_number)==40 && offsetof(struct loop_info64,lo_flags)==52 && offsetof(struct loop_info64,lo_file_name)==56 && offsetof(struct loop_info64,lo_init)==216,"locked loop_info64 offsets");
_Static_assert(LO_FLAGS_READ_ONLY == 1 && LO_FLAGS_AUTOCLEAR == 4, "loop flags");
_Static_assert(LOOP_SET_FD == 0x4c00 && LOOP_CLR_FD == 0x4c01, "loop requests");
_Static_assert(LOOP_SET_STATUS64 == 0x4c04 && LOOP_GET_STATUS64 == 0x4c05,
               "loop 64-bit requests");

#define CACHE_BYTES (384ULL * 1024 * 1024)
#define ROOT_BYTES (16ULL * 1024 * 1024)
#define RELEASE "5.10.160-rt89-g9f9e9d18574d-dirty"
#define IMAGE_SHA "e7a95d9fc5a3e87f407145cbadaf0cb2c787c637b2311c4ff551a73f8b8fa457"
#define BB_SHA "514c3fa48e538283aea7881cc7c54c4a77c855db09c05008fef9587f2ac906a1"
#define CODEC_SHA "18fd4744d881e46661d16ad60112f395262b6a6e97ce83f246a4334f6448234c"
#define PTY_SHA "5eb5fd9aba8133933dce602d5e0dbd3acf5f1829f700615dc77a67b5f1d0cbda"
#define IMAGE_FILE "/backing-cache/rtctrl-rcu-reset-20261004/Image"
#define ROOT_FILE "/backing-cache/rtctrl-pid1-20261005-v3/rootfs-pid1.ext4"
#define RO_FLAGS (MS_RDONLY | MS_NOSUID | MS_NODEV)
#define TMPFS_MAGIC 0x01021994UL
#define EXT4_MAGIC 0xef53UL
#define STATE_MAGIC UINT64_C(0x5254435049443101)
#define PF_KTHREAD 0x00200000ULL

enum phase { BOOTSTRAP = 1, ROOT = 2, RETURN = 3, RAM = 4 };
struct hashes { char image[65], busybox[65], pid1[65], rootfs[65], codec[65], pty[65]; };
enum mount_slot { INITIAL_MOUNT, ROOT_MOUNT, ISLAND_MOUNT, CACHE_MOUNT,
                  DEV_MOUNT, PTS_MOUNT, PROC_MOUNT, SYS_MOUNT, TMP_MOUNT,
                  RUN_MOUNT, MOUNT_COUNT };
struct mount_record { uint64_t device; uint32_t id,parent; char type[16]; };
struct state {
    uint64_t magic, cache_dev, backing_dev, backing_inode, root_dev;
    uint32_t version, phase, forward, backward, pivoted, root_unmounted;
    uint32_t loop_detached, cache_unmounted, loop_owned, loop_number;
    struct hashes hashes;
    struct mount_record mounts[MOUNT_COUNT];
    uint32_t mounts_saved;
};
_Static_assert(sizeof(struct mount_record)==32 && offsetof(struct state,mounts)==472 &&
               offsetof(struct state,mounts_saved)==792 && sizeof(struct state)==800,
               "native state v2 layout");
static struct state st;
static int error_number;
static char error_step[128];
static int root_entered, island_entered, bootstrap_island, switch_moved, pivot_chroot_needed;
static int state_verified;
static volatile sig_atomic_t child_pending;
static pid_t owned_child;
static unsigned long long owned_start;
static const char *const names[] = {".backing-cache", "dev", "proc", "sys", "tmp", "run"};
static const char *const mount_types[MOUNT_COUNT] =
    {"", "ext4", "tmpfs", "ext4", "devtmpfs", "devpts", "proc", "sysfs", "tmpfs", "tmpfs"};
/* Exact --list inventory of the SHA-locked BusyBox; ash has no standalone lookup. */
static const char *const island_applets[] = {
    "[", "[[", "ash", "cat", "chmod", "chown", "chroot", "cp", "cpio", "cttyhack",
    "dd", "df", "dmesg", "echo", "grep", "gunzip", "gzip", "halt", "head", "hexdump",
    "insmod", "ip", "ln", "losetup", "ls", "mkdir", "modprobe", "mount", "mv", "ping",
    "poweroff", "printf", "ps", "readlink", "reboot", "rm", "rmmod", "sed", "setsid",
    "sh", "sha256sum", "sleep", "stat", "sync", "tail", "tar", "test", "touch",
    "udhcpc", "umount", "uname", "zcat"
};
_Static_assert(sizeof(island_applets)/sizeof(island_applets[0])==52,
               "locked BusyBox applet count");

/* FIPS 180-4 SHA256; no library or external command dependency. */
struct sha256 { uint32_t h[8]; uint64_t bytes; unsigned char block[64]; size_t used; };
static uint32_t rr(uint32_t a, unsigned b) { return (a >> b) | (a << (32 - b)); }
static void sha_block(struct sha256 *s, const unsigned char *p)
{
    static const uint32_t k[64] = {
        0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,
        0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,
        0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,
        0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,
        0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,
        0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,
        0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,
        0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2 };
    uint32_t w[64], a,b,c,d,e,f,g,h;
    for (size_t i=0;i<16;i++) w[i]=(uint32_t)p[4*i]<<24|(uint32_t)p[4*i+1]<<16|(uint32_t)p[4*i+2]<<8|p[4*i+3];
    for (size_t i=16;i<64;i++) w[i]=w[i-16]+(rr(w[i-15],7)^rr(w[i-15],18)^(w[i-15]>>3))+w[i-7]+(rr(w[i-2],17)^rr(w[i-2],19)^(w[i-2]>>10));
    a=s->h[0];b=s->h[1];c=s->h[2];d=s->h[3];e=s->h[4];f=s->h[5];g=s->h[6];h=s->h[7];
    for (size_t i=0;i<64;i++) {
        uint32_t t1=h+(rr(e,6)^rr(e,11)^rr(e,25))+((e&f)^((~e)&g))+k[i]+w[i];
        uint32_t t2=(rr(a,2)^rr(a,13)^rr(a,22))+((a&b)^(a&c)^(b&c));
        h=g;g=f;f=e;e=d+t1;d=c;c=b;b=a;a=t1+t2;
    }
    s->h[0]+=a;s->h[1]+=b;s->h[2]+=c;s->h[3]+=d;s->h[4]+=e;s->h[5]+=f;s->h[6]+=g;s->h[7]+=h;
}
static void sha_init(struct sha256 *s)
{
    *s=(struct sha256){ .h={0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19} };
}
static void sha_add(struct sha256 *s, const unsigned char *p, size_t n)
{
    s->bytes+=n;
    while(n) {
        size_t k=64-s->used;
        if(k>n) k=n;
        memcpy(s->block+s->used,p,k);s->used+=k;p+=k;n-=k;
        if(s->used==64) { sha_block(s,s->block);s->used=0; }
    }
}
static void sha_end(struct sha256 *s, char out[65])
{
    uint64_t bits=s->bytes*8;
    unsigned char pad[128]={0x80};
    size_t n=s->used<56?56-s->used:120-s->used;
    sha_add(s,pad,n);
    for(size_t i=0;i<8;i++) pad[i]=(unsigned char)(bits>>(56-i*8));
    sha_add(s,pad,8);
    for(size_t i=0;i<8;i++) (void)snprintf(out+8*i,9,"%08x",s->h[i]);
    out[64]=0;
}

static int fail(const char *step)
{
    if(!error_step[0]) {
        error_number=errno?errno:EINVAL;
        (void)snprintf(error_step,sizeof(error_step),"%s",step);
    }
    return -1;
}
static int invalid(const char *step) { errno=EINVAL;return fail(step); }
static int checked_close(int fd)
{
    return close(fd)<0?fail("close"):0;
}
static int text_file(const char *path, char *buf, size_t size)
{
    int fd=open(path,O_RDONLY|O_NOFOLLOW|O_CLOEXEC);
    if(fd<0) return fail(path);
    size_t used=0;
    int result=0;
    while(used<size-1) {
        ssize_t n=read(fd,buf+used,size-1-used);
        if(n<0) { if(errno==EINTR) continue;result=fail("read text");break; }
        if(!n) break;
        used+=(size_t)n;
    }
    if(used==size-1) result=invalid("text file too long");
    buf[used]=0;
    if(checked_close(fd)<0) result=-1;
    return result;
}
static int exact_read(int fd, void *data, size_t count)
{
    size_t n=0;
    while(n<count) {
        ssize_t k=read(fd,(char *)data+n,count-n);
        if(k<0 && errno==EINTR) continue;
        if(k<=0) return fail("short/read error");
        n+=(size_t)k;
    }
    return 0;
}
static int exact_write(int fd, const void *data, size_t count)
{
    size_t n=0;
    while(n<count) {
        ssize_t k=write(fd,(const char *)data+n,count-n);
        if(k<0 && errno==EINTR) continue;
        if(k<=0) return fail("short/write error");
        n+=(size_t)k;
    }
    return 0;
}
static int digest_fd(int fd, const char *expected)
{
    struct sha256 s;
    unsigned char buf[16384];
    char actual[65];
    sha_init(&s);
    if(lseek(fd,0,SEEK_SET)<0) return fail("hash lseek");
    for(;;) {
        ssize_t n=read(fd,buf,sizeof(buf));
        if(n<0) { if(errno==EINTR) continue;return fail("hash read"); }
        if(!n) break;
        sha_add(&s,buf,(size_t)n);
    }
    sha_end(&s,actual);
    if(strcmp(actual,expected)) return invalid("SHA mismatch");
    return lseek(fd,0,SEEK_SET)<0?fail("hash rewind"):0;
}
static int checked_file(const char *path, const char *expected, uint64_t limit,
                        struct stat *sb, int proc_exe)
{
    int flags=O_RDONLY|O_CLOEXEC;
    if(!proc_exe) flags|=O_NOFOLLOW;
    int fd=open(path,flags);
    if(fd<0) return fail(path);
    if(fstat(fd,sb)<0) { fail("file fstat");checked_close(fd);return -1; }
    if(!S_ISREG(sb->st_mode)||sb->st_uid!=0||sb->st_gid!=0||sb->st_nlink!=1||
       sb->st_size<=0||(uint64_t)sb->st_size>limit||digest_fd(fd,expected)<0) {
        invalid("ordinary root file identity");checked_close(fd);return -1;
    }
    return fd;
}
static int checked_hash(const char *path, const char *expected, int proc_exe)
{
    struct stat sb;
    int fd=checked_file(path,expected,64ULL*1024*1024,&sb,proc_exe);
    return fd<0?-1:checked_close(fd);
}
static int hashes_read(void)
{
    char content[1024];
    if(text_file("/etc/rtctrl/manifest",content,sizeof(content))<0) return -1;
    char *save=NULL,*line=strtok_r(content,"\n",&save);
    if(!line||strcmp(line,"RTCTRL_PID1_V1")) return invalid("manifest version");
    char *fields[]={st.hashes.image,st.hashes.busybox,st.hashes.pid1,st.hashes.rootfs,st.hashes.codec,st.hashes.pty};
    const char *keys[]={"image=","busybox=","pid1=","rootfs=","codec=","pty="};
    for(size_t i=0;i<6;i++) {
        line=strtok_r(NULL,"\n",&save);
        size_t n=strlen(keys[i]);
        if(!line||strncmp(line,keys[i],n)||strlen(line+n)!=64) return invalid("manifest field");
        for(size_t k=0;k<64;k++) if(!((line[n+k]>='0'&&line[n+k]<='9')||(line[n+k]>='a'&&line[n+k]<='f'))) return invalid("manifest hex");
        memcpy(fields[i],line+n,65);
    }
    if(strtok_r(NULL,"\n",&save)||strcmp(st.hashes.image,IMAGE_SHA)||strcmp(st.hashes.busybox,BB_SHA)||strcmp(st.hashes.codec,CODEC_SHA)||strcmp(st.hashes.pty,PTY_SHA)) return invalid("manifest locked input");
    return 0;
}
static const char *island(void)
{
    if(switch_moved&&!root_entered) return "./.ram-return";
    return island_entered?"":(root_entered?"/.ram-return":"/newroot/.ram-return");
}
static void state_path(char out[256]) { (void)snprintf(out,256,"%s/state",island()); }
static int state_save(void)
{
    char path[256];state_path(path);
    int fd=open(path,O_WRONLY|O_CREAT|O_TRUNC|O_NOFOLLOW|O_CLOEXEC,0600);
    if(fd<0) return fail("state open write");
    struct stat sb;
    int r=0;
    if(fstat(fd,&sb)<0) r=fail("state fstat");
    else if(!S_ISREG(sb.st_mode)||sb.st_uid||sb.st_gid||sb.st_nlink!=1) r=invalid("state ownership");
    else if(exact_write(fd,&st,sizeof(st))<0||fsync(fd)<0) r=fail("state persist");
    if(checked_close(fd)<0) r=-1;
    return r;
}
static int state_read(void)
{
    struct statfs fs;struct stat island_stat;
    char path[256];state_path(path);
    if(stat(island(),&island_stat)<0||statfs(island(),&fs)<0) return fail("state tmpfs statfs");
    if((unsigned long)fs.f_type!=TMPFS_MAGIC||!S_ISDIR(island_stat.st_mode)||island_stat.st_uid||island_stat.st_gid) return invalid("state island not tmpfs");
    int fd=open(path,O_RDONLY|O_NOFOLLOW|O_CLOEXEC);
    if(fd<0) return fail("state open read");
    struct stat sb;
    int r=0;
    if(fstat(fd,&sb)<0) r=fail("state fstat");
    else if(!S_ISREG(sb.st_mode)||sb.st_uid||sb.st_gid||sb.st_nlink!=1||sb.st_size!=(off_t)sizeof(st)||sb.st_dev!=island_stat.st_dev) r=invalid("state identity");
    else if(exact_read(fd,&st,sizeof(st))<0) r=-1;
    if(checked_close(fd)<0) r=-1;
    if(r<0) return -1;
    char *fields[]={st.hashes.image,st.hashes.busybox,st.hashes.pid1,st.hashes.rootfs,st.hashes.codec,st.hashes.pty};
    for(size_t i=0;i<6;i++) {
        if(fields[i][64]) return invalid("state hash terminator");
        for(size_t j=0;j<64;j++) if(!((fields[i][j]>='0'&&fields[i][j]<='9')||(fields[i][j]>='a'&&fields[i][j]<='f'))) return invalid("state hash hex");
    }
    if(st.magic!=STATE_MAGIC||st.version!=2||st.loop_number>255||st.loop_owned!=1||st.forward!=63||st.backward>63||(st.backward&(st.backward+1))||st.pivoted>1||st.root_unmounted>1||st.loop_detached>1||st.cache_unmounted>1||st.phase<ROOT||st.phase>RAM||major((dev_t)st.cache_dev)!=179||st.backing_dev!=st.cache_dev||!st.backing_inode||st.root_dev!=(uint64_t)makedev(7,st.loop_number)||st.root_dev==(uint64_t)island_stat.st_dev||strcmp(st.hashes.image,IMAGE_SHA)||strcmp(st.hashes.busybox,BB_SHA)||strcmp(st.hashes.codec,CODEC_SHA)||strcmp(st.hashes.pty,PTY_SHA)) return invalid("state contract");
    if(st.mounts_saved!=1||st.mounts[ROOT_MOUNT].device!=st.root_dev||
       st.mounts[CACHE_MOUNT].device!=st.cache_dev||
       st.mounts[ISLAND_MOUNT].device!=(uint64_t)island_stat.st_dev||
       (st.pivoted&&st.backward!=63)||(st.root_unmounted&&!st.pivoted)||
       (st.loop_detached&&!st.root_unmounted)||(st.cache_unmounted&&!st.loop_detached)||
       (st.phase==RAM&&!st.cache_unmounted)) return invalid("state mount contract");
    for(size_t i=0;i<MOUNT_COUNT;i++) {
        struct mount_record *m=&st.mounts[i];
        if(!m->id||!m->parent||!memchr(m->type,0,sizeof(m->type)))
            return invalid("state mount record");
        if(i==INITIAL_MOUNT) {
            if(strcmp(m->type,"rootfs")&&strcmp(m->type,"tmpfs")&&strcmp(m->type,"ramfs"))
                return invalid("state initial mount type");
        } else if(strcmp(m->type,mount_types[i])) return invalid("state mount type");
        for(size_t j=0;j<i;j++) if(m->id==st.mounts[j].id) return invalid("state duplicate mount ID");
        uint32_t parent=i==INITIAL_MOUNT?m->parent:
            (i==ISLAND_MOUNT?st.mounts[ROOT_MOUNT].id:
             (i==PTS_MOUNT?st.mounts[DEV_MOUNT].id:st.mounts[INITIAL_MOUNT].id));
        if(m->parent!=parent) return invalid("state original mount parent");
    }
    state_verified=1;
    return 0;
}
static const char *live_mount(size_t index, char buf[256])
{
    if(island_entered) (void)snprintf(buf,256,"/%s",index==0?"backing-cache":names[index]);
    else if(switch_moved&&!root_entered) (void)snprintf(buf,256,"./%s",names[index]);
    else if(st.backward&(1u<<index)) (void)snprintf(buf,256,"%s/%s",island(),index==0?"backing-cache":names[index]);
    else if(root_entered||(st.forward&(1u<<index))) (void)snprintf(buf,256,"%s/%s",root_entered?"":"/newroot",names[index]);
    else (void)snprintf(buf,256,"/%s",index==0?"backing-cache":names[index]);
    return buf;
}
struct mount_entry {
    unsigned id,parent,major,minor;
    char root[256],point[256],options[256],type[64],source[256],super[256];
};
static int mount_parse(char *line,struct mount_entry *m)
{
    char *sep=strstr(line," - ");
    if(!sep||sscanf(line,"%u %u %u:%u %255s %255s %255s",
       &m->id,&m->parent,&m->major,&m->minor,m->root,m->point,m->options)!=7||
       sscanf(sep+3,"%63s %255s %255s",m->type,m->source,m->super)!=3||
       !m->id||!m->parent||strstr(line," shared:")||strstr(line," master:")||
       strstr(line," propagate_from:")||strstr(line," unbindable"))
        return invalid("mountinfo malformed/shared");
    return 0;
}
static int mount_option(const char *options,const char *option)
{
    size_t n=strlen(option);
    for(const char *p=options;p;) {
        if(!strncmp(p,option,n)&&(p[n]==0||p[n]==',')) return 1;
        p=strchr(p,',');if(p) p++;
    }
    return 0;
}
static int mount_read(char content[32768])
{
    char proc[256];live_mount(2,proc);
    size_t n=strlen(proc);(void)snprintf(proc+n,sizeof(proc)-n,"/1/mountinfo");
    return text_file(proc,content,32768);
}
static int mount_identity(const char *target, const char *type, unsigned maj,
                          unsigned min, int readonly)
{
    char content[32768];
    if(mount_read(content)<0) return -1;
    char *save=NULL;
    unsigned matches=0;
    for(char *line=strtok_r(content,"\n",&save);line;line=strtok_r(NULL,"\n",&save)) {
        struct mount_entry m;
        if(mount_parse(line,&m)<0) return -1;
        if(!strcmp(m.point,target)) {
            if(++matches!=1||strcmp(m.type,type)||m.major!=maj||m.minor!=min||strcmp(m.root,"/"))
                return invalid("mount identity/duplicate target");
            if(readonly&&(!mount_option(m.options,"ro")||!mount_option(m.super,"ro")))
                return invalid("mount/superblock not readonly");
        }
    }
    return matches==1?0:invalid("mount missing");
}
static int mount_target(size_t slot,char path[300])
{
    if(slot==INITIAL_MOUNT) {
        if(root_entered||island_entered) return 0;
        (void)snprintf(path,300,"/");return 1;
    }
    if(slot==ROOT_MOUNT) {
        if(st.root_unmounted) return 0;
        (void)snprintf(path,300,"%s",island_entered?"/old-root":(root_entered?"/":"/newroot"));
        return 1;
    }
    if(slot==ISLAND_MOUNT) {
        (void)snprintf(path,300,"%s",island_entered?"/":island());return 1;
    }
    if(slot==CACHE_MOUNT&&st.cache_unmounted) return 0;
    size_t index=slot==CACHE_MOUNT?0:(slot==DEV_MOUNT||slot==PTS_MOUNT?1:slot-PROC_MOUNT+2);
    char base[256];live_mount(index,base);
    (void)snprintf(path,300,"%s%s",base,slot==PTS_MOUNT?"/pts":"");
    return 1;
}
static unsigned mount_parent(size_t slot)
{
    if(slot==INITIAL_MOUNT) return st.mounts[slot].parent;
    if(slot==ROOT_MOUNT) return st.mounts[island_entered?ISLAND_MOUNT:INITIAL_MOUNT].id;
    if(slot==ISLAND_MOUNT) return st.mounts[island_entered?INITIAL_MOUNT:ROOT_MOUNT].id;
    if(slot==PTS_MOUNT) return st.mounts[DEV_MOUNT].id;
    size_t index=slot==CACHE_MOUNT?0:(slot==DEV_MOUNT?1:slot-PROC_MOUNT+2);
    if(island_entered||(st.backward&(1u<<index))) return st.mounts[ISLAND_MOUNT].id;
    return st.mounts[(root_entered||(st.forward&(1u<<index)))?ROOT_MOUNT:INITIAL_MOUNT].id;
}
static int mount_table(int capture)
{
    char content[32768];unsigned seen[MOUNT_COUNT]={0};
    if((!capture&&st.mounts_saved!=1)||mount_read(content)<0) return invalid("mount table unavailable");
    char *save=NULL;
    for(char *line=strtok_r(content,"\n",&save);line;line=strtok_r(NULL,"\n",&save)) {
        struct mount_entry m;
        if(mount_parse(line,&m)<0) return -1;
        size_t slot;
        for(slot=0;slot<MOUNT_COUNT;slot++) {
            char target[300];
            if(mount_target(slot,target)&&!strcmp(m.point,target)) break;
        }
        if(slot==MOUNT_COUNT||++seen[slot]!=1) return invalid("unowned/duplicate mount target");
        if(strcmp(m.root,"/")) return invalid("mount root is not whole filesystem");
        if(slot==INITIAL_MOUNT) {
            if(strcmp(m.type,"rootfs")&&strcmp(m.type,"tmpfs")&&strcmp(m.type,"ramfs"))
                return invalid("initial mount type");
        } else if(strcmp(m.type,mount_types[slot])) return invalid("mount filesystem type");
        if((slot==ROOT_MOUNT||slot==CACHE_MOUNT)&&
           (!mount_option(m.options,"ro")||!mount_option(m.super,"ro")))
            return invalid("mount table writable ext4");
        struct mount_record *record=&st.mounts[slot];
        uint64_t device=(uint64_t)makedev(m.major,m.minor);
        if(capture) {
            struct stat sb;
            if(stat(m.point,&sb)<0) return fail("capture mount stat");
            if(!S_ISDIR(sb.st_mode)||(uint64_t)sb.st_dev!=device) return invalid("capture mount device");
            *record=(struct mount_record){.device=device,.id=m.id,.parent=m.parent};
            size_t type_length=strlen(m.type);
            if(type_length>=sizeof(record->type)) return invalid("mount type too long");
            memcpy(record->type,m.type,type_length+1);
        } else if(record->device!=device||record->id!=m.id||strcmp(record->type,m.type)||
                  m.parent!=mount_parent(slot)) return invalid("mount ID/device/parent changed");
    }
    for(size_t i=0;i<MOUNT_COUNT;i++) {
        char path[300];unsigned want=(unsigned)mount_target(i,path);
        if(seen[i]!=want) return invalid("mount table missing/extra entry");
        if(capture) {
            for(size_t j=0;j<i;j++) if(st.mounts[i].id==st.mounts[j].id)
                return invalid("duplicate mount ID");
            if(st.mounts[i].parent!=mount_parent(i)) return invalid("capture mount parent");
        }
    }
    if(capture) {
        if(st.mounts[ROOT_MOUNT].device!=st.root_dev||st.mounts[CACHE_MOUNT].device!=st.cache_dev)
            return invalid("captured ext4 device changed");
        st.mounts_saved=1;state_verified=1;
    }
    return 0;
}
static int fd_guard(void)
{
    char proc[256];live_mount(2,proc);
    size_t n=strlen(proc);(void)snprintf(proc+n,sizeof(proc)-n,"/1/fd");
    DIR *d=opendir(proc);
    if(!d) return fail("FD directory");
    int own=dirfd(d),r=0;errno=0;
    struct dirent *e;
    while((e=readdir(d))) {
        char *end;long fd=strtol(e->d_name,&end,10);
        if(!*e->d_name||*end) continue;
        if(fd>2&&fd!=own) { r=invalid("inherited extra FD");break; }
    }
    if(errno && !r) r=fail("FD readdir");
    if(closedir(d)<0) r=fail("FD closedir");
    for(int i=0;i<3&&!r;i++) {
        struct stat sb;
        if(fstat(i,&sb)<0) r=fail("console fstat");
        else if(!S_ISCHR(sb.st_mode)||major(sb.st_rdev)!=5||minor(sb.st_rdev)!=1) r=invalid("stdio not console");
        else {
            int flags=fcntl(i,F_GETFD);
            if(flags<0) r=fail("stdio FD flags");
            else if(flags&FD_CLOEXEC) r=invalid("stdio would close on exec");
        }
    }
    return r;
}
struct process { pid_t pid, parent, group, session; unsigned long long flags,start; };
static int process_stat(const char *proc, pid_t pid, struct process *p)
{
    char path[300],buf[4096];(void)snprintf(path,sizeof(path),"%s/%ld/stat",proc,(long)pid);
    if(text_file(path,buf,sizeof(buf))<0) return -1;
    char *end=strrchr(buf,')');
    if(!end||end[1]!=' ') return invalid("process stat syntax");
    char *save=NULL,*token=strtok_r(end+2," ", &save);
    p->pid=pid;
    for(int field=3;field<=22;field++) {
        if(!token) return invalid("process stat fields");
        if(field==4||field==5||field==6||field==9||field==22) {
            char *tail;errno=0;unsigned long long v=strtoull(token,&tail,10);
            if(errno||*tail) return invalid("process stat number");
            if(field==4) p->parent=(pid_t)v;
            if(field==5) p->group=(pid_t)v;
            if(field==6) p->session=(pid_t)v;
            if(field==9) p->flags=v;
            if(field==22) p->start=v;
        }
        token=strtok_r(NULL," ",&save);
    }
    return 0;
}
static int reap(void)
{
    int status;pid_t p;
    do {
        p=waitpid(-1,&status,WNOHANG);
        if(p<0&&errno==EINTR) continue;
        if(p==owned_child) { owned_child=0;owned_start=0; }
    } while(p>0||(p<0&&errno==EINTR));
    child_pending=0;
    if(p<0&&errno!=ECHILD&&errno!=EINTR) return fail("orphan waitpid");
    return 0;
}
static int process_guard(void)
{
    char proc[256];live_mount(2,proc);
    if(reap()<0) return -1;
    if(owned_child) return invalid("owned session still live");
    DIR *d=opendir(proc);
    if(!d) return fail("process directory");
    int r=0;struct dirent *e;
    for(;;) {
        errno=0;e=readdir(d);
        if(!e) { if(errno) r=fail("process readdir");break; }
        char *end;long pid=strtol(e->d_name,&end,10);
        if(!*e->d_name||*end||pid<=1) continue;
        struct process p;
        if(process_stat(proc,(pid_t)pid,&p)<0) { r=-1;break; }
        if(!(p.flags&PF_KTHREAD)) {
            dprintf(2,"UNOWNED_PROCESS pid=%ld start=%llu session=%ld\n",pid,p.start,(long)p.session);
            r=invalid("live user process blocks return");break;
        }
    }
    if(closedir(d)<0) r=fail("process closedir");
    return r;
}
static int loop_fd(int expected_bound)
{
    char dev[256],path[300];live_mount(1,dev);
    (void)snprintf(path,sizeof(path),"%s/loop%u",dev,st.loop_number);
    int fd=open(path,O_RDONLY|O_NOFOLLOW|O_CLOEXEC|O_NONBLOCK);
    if(fd<0) return fail("loop open");
    struct stat sb;struct loop_info64 li;
    if(fstat(fd,&sb)<0) { fail("loop fstat");checked_close(fd);return -1; }
    if(!S_ISBLK(sb.st_mode)||major(sb.st_rdev)!=7||minor(sb.st_rdev)!=st.loop_number) { invalid("loop block identity");checked_close(fd);return -1; }
    memset(&li,0,sizeof(li));
    int r=ioctl(fd,LOOP_GET_STATUS64,&li);
    if(expected_bound) {
        if(r<0) { fail("loop get status");checked_close(fd);return -1; }
        if(li.lo_device!=st.backing_dev||li.lo_inode!=st.backing_inode||li.lo_rdevice||li.lo_offset||li.lo_sizelimit||li.lo_encrypt_type||li.lo_encrypt_key_size||li.lo_flags!=LO_FLAGS_READ_ONLY||li.lo_number!=st.loop_number) { invalid("loop binding identity");checked_close(fd);return -1; }
    } else if(r>=0||errno!=ENXIO) { invalid("loop not empty");checked_close(fd);return -1; }
    return fd;
}
static int copy_checked(const char *src, const char *dst, const char *hash)
{
    struct stat sb;int in=checked_file(src,hash,64ULL*1024*1024,&sb,0);
    if(in<0) return -1;
    int out=open(dst,O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW|O_CLOEXEC,0755);
    if(out<0) { fail("island copy open");checked_close(in);return -1; }
    int r=0;unsigned char buf[16384];
    for(;;) {
        ssize_t n=read(in,buf,sizeof(buf));
        if(n<0) { if(errno==EINTR) continue;r=fail("island copy read");break; }
        if(!n) break;
        if(exact_write(out,buf,(size_t)n)<0) { r=-1;break; }
    }
    if(fsync(out)<0) r=fail("island copy fsync");
    if(checked_close(out)<0) r=-1;
    if(checked_close(in)<0) r=-1;
    if(!r) r=checked_hash(dst,hash,0);
    return r;
}
static int cache_check(void)
{
    char buf[4096],*end;
    if(text_file("/sys/class/block/mmcblk0p12/uevent",buf,sizeof(buf))<0) return -1;
    if(!strstr(buf,"\nPARTNAME=cache\n") && strncmp(buf,"PARTNAME=cache\n",15)) return invalid("cache PARTNAME");
    if(text_file("/sys/class/block/mmcblk0p12/size",buf,sizeof(buf))<0) return -1;
    errno=0;unsigned long long sectors=strtoull(buf,&end,10);
    if(errno||strcmp(end,"\n")||sectors!=786432) return invalid("cache sectors");
    if(text_file("/sys/class/block/mmcblk0p12/dev",buf,sizeof(buf))<0) return -1;
    unsigned ma,mi;char extra;
    if(sscanf(buf,"%u:%u%c",&ma,&mi,&extra)!=3||extra!='\n'||ma!=179) return invalid("cache sysdev");
    int fd=open("/dev/mmcblk0p12",O_RDONLY|O_NOFOLLOW|O_CLOEXEC|O_NONBLOCK);
    if(fd<0) return fail("cache block open");
    struct stat sb;uint64_t bytes=0;int r=0;
    if(fstat(fd,&sb)<0) r=fail("cache fstat");
    else if(!S_ISBLK(sb.st_mode)||sb.st_rdev!=makedev(ma,mi)) r=invalid("cache block identity");
    else if(ioctl(fd,BLKGETSIZE64,&bytes)<0) r=fail("cache size ioctl");
    else if(bytes!=CACHE_BYTES) r=invalid("cache byte size");
    else st.cache_dev=sb.st_rdev;
    if(checked_close(fd)<0) r=-1;
    return r;
}
static int clean_image(int fd)
{
    unsigned char super[1024];
    if(lseek(fd,1024,SEEK_SET)<0||exact_read(fd,super,sizeof(super))<0) return fail("rootfs superblock read");
    uint16_t magic=(uint16_t)super[56]|(uint16_t)super[57]<<8;
    uint16_t state=(uint16_t)super[58]|(uint16_t)super[59]<<8;
    uint32_t incompat=(uint32_t)super[96]|(uint32_t)super[97]<<8|(uint32_t)super[98]<<16|(uint32_t)super[99]<<24;
    if(magic!=EXT4_MAGIC||state!=1||(incompat&4)) return invalid("rootfs dirty/needs_recovery");
    return 0;
}
static int bootstrap(void)
{
    st.magic=STATE_MAGIC;st.version=2;st.phase=BOOTSTRAP;
    if(mount(NULL,"/",NULL,MS_REC|MS_PRIVATE,NULL)<0) return fail("private root");
    if(mount("devtmpfs","/dev","devtmpfs",MS_NOSUID,"mode=0755")<0) return fail("mount dev");
    if(mount("proc","/proc","proc",MS_NOSUID|MS_NODEV|MS_NOEXEC,NULL)<0) return fail("mount proc");
    if(mount("sysfs","/sys","sysfs",MS_NOSUID|MS_NODEV|MS_NOEXEC,NULL)<0) return fail("mount sys");
    if(mount("tmpfs","/tmp","tmpfs",MS_NOSUID|MS_NODEV,"mode=1777,size=8m")<0) return fail("mount tmp");
    if(mount("tmpfs","/run","tmpfs",MS_NOSUID|MS_NODEV|MS_NOEXEC,"mode=0755,size=1m")<0) return fail("mount run");
    if(mkdir("/dev/pts",0755)<0&&errno!=EEXIST) return fail("devpts directory");
    if(mount("devpts","/dev/pts","devpts",MS_NOSUID|MS_NOEXEC,"mode=0620,ptmxmode=0666,newinstance")<0) return fail("mount devpts");
    /* devtmpfs ptmx is a device node. The explicit symlink selects this instance. */
    if(unlink("/dev/ptmx")<0&&errno!=ENOENT) return fail("ptmx unlink");
    if(symlink("pts/ptmx","/dev/ptmx")<0) return fail("ptmx symlink");
    struct utsname un;
    if(uname(&un)<0) return fail("uname");
    if(strcmp(un.release,RELEASE)||strcmp(un.machine,"aarch64")) return invalid("kernel release/architecture");
    if(hashes_read()<0||checked_hash("/init",st.hashes.pid1,0)<0||checked_hash("/bin/busybox",BB_SHA,0)<0||cache_check()<0) return -1;
    if(mount("/dev/mmcblk0p12","/backing-cache","ext4",RO_FLAGS|MS_NOEXEC,"noload")<0) return fail("mount cache RO noload");
    if(mount_identity("/backing-cache","ext4",major(st.cache_dev),minor(st.cache_dev),1)<0||checked_hash(IMAGE_FILE,IMAGE_SHA,0)<0) return -1;
    struct stat backing;
    int image=checked_file(ROOT_FILE,st.hashes.rootfs,ROOT_BYTES,&backing,0);
    if(image<0) return -1;
    if((uint64_t)backing.st_size!=ROOT_BYTES||backing.st_dev!=st.cache_dev||clean_image(image)<0) { invalid("rootfs backing identity");checked_close(image);return -1; }
    st.backing_dev=backing.st_dev;st.backing_inode=backing.st_ino;
    int ctl=open("/dev/loop-control",O_RDONLY|O_NOFOLLOW|O_CLOEXEC|O_NONBLOCK);
    if(ctl<0) { fail("loop-control open");checked_close(image);return -1; }
    struct stat control;
    if(fstat(ctl,&control)<0) { fail("loop-control fstat");checked_close(ctl);checked_close(image);return -1; }
    if(!S_ISCHR(control.st_mode)||control.st_rdev!=makedev(10,237)) { invalid("loop-control identity");checked_close(ctl);checked_close(image);return -1; }
    int number=ioctl(ctl,LOOP_CTL_GET_FREE);
    if(number<0||number>255) { if(number<0) fail("loop allocate");else invalid("loop allocation range");checked_close(ctl);checked_close(image);return -1; }
    st.loop_number=(uint32_t)number;
    if(checked_close(ctl)<0) { checked_close(image);return -1; }
    int loop=loop_fd(0);
    if(loop<0) { checked_close(image);return -1; }
    if(ioctl(loop,LOOP_SET_FD,image)<0) { fail("loop set fd");checked_close(loop);checked_close(image);return -1; }
    st.loop_owned=1;
    struct loop_info64 li={.lo_flags=LO_FLAGS_READ_ONLY};
    (void)snprintf((char *)li.lo_file_name,sizeof(li.lo_file_name),"rootfs-pid1.ext4");
    int r=ioctl(loop,LOOP_SET_STATUS64,&li)<0?fail("loop readonly status"):0;
    if(checked_close(loop)<0) r=-1;
    if(checked_close(image)<0) r=-1;
    if(r<0) return -1;
    loop=loop_fd(1);
    if(loop<0||checked_close(loop)<0) return -1;
    char device[64];(void)snprintf(device,sizeof(device),"/dev/loop%u",st.loop_number);
    if(mount(device,"/newroot","ext4",RO_FLAGS,"noload")<0) return fail("mount root RO noload");
    struct stat sb;
    if(stat("/newroot",&sb)<0) return fail("root stat");
    st.root_dev=sb.st_dev;
    if(st.root_dev!=makedev(7,st.loop_number)||mount_identity("/newroot","ext4",7,st.loop_number,1)<0||checked_hash("/newroot/bin/pid1",st.hashes.pid1,0)<0||checked_hash("/newroot/bin/busybox",BB_SHA,0)<0||checked_hash("/newroot/usr/bin/codec-test",CODEC_SHA,0)<0||checked_hash("/newroot/usr/bin/pty-test",PTY_SHA,0)<0) return invalid("new root identity");
    if(mount("tmpfs","/newroot/.ram-return","tmpfs",MS_NOSUID|MS_NODEV,"mode=0700,size=8m")<0) return fail("mount return island");
    bootstrap_island=1;
    const char *dirs[]={"bin","backing-cache","dev","proc","sys","tmp","run","old-root"};
    for(size_t i=0;i<sizeof(dirs)/sizeof(dirs[0]);i++) {
        char path[256];(void)snprintf(path,sizeof(path),"%s/%s",island(),dirs[i]);
        if(mkdir(path,0755)<0) return fail("island directory");
    }
    if(copy_checked("/init","/newroot/.ram-return/bin/pid1",st.hashes.pid1)<0||
       copy_checked("/bin/busybox","/newroot/.ram-return/bin/busybox",BB_SHA)<0) return -1;
    for(size_t i=0;i<sizeof(island_applets)/sizeof(island_applets[0]);i++) {
        char path[256];
        (void)snprintf(path,sizeof(path),"%s/bin/%s",island(),island_applets[i]);
        if(symlink("busybox",path)<0) return fail("island applet symlink");
    }
    if(mount_table(1)<0||state_save()<0||process_guard()<0||fd_guard()<0) return -1;
    for(size_t i=0;i<6;i++) {
        char src[256],dst[256];live_mount(i,src);(void)snprintf(dst,sizeof(dst),"/newroot/%s",names[i]);
        if(mount(src,dst,NULL,MS_MOVE,NULL)<0) return fail("forward mount move");
        st.forward|=1u<<i;
        if(mount_table(0)<0||state_save()<0) return -1;
    }
    st.phase=ROOT;
    if(state_save()<0||fd_guard()<0) return -1;
    if(chdir("/newroot")<0) return fail("switch chdir");
    if(mount(".","/",NULL,MS_MOVE,NULL)<0) return fail("switch root move");
    switch_moved=1;
    if(chroot(".")<0) return fail("switch chroot");
    root_entered=1;
    if(chdir("/")<0) return fail("switch root cwd");
    char *const args[]={"/bin/pid1","root",NULL};char *const env[]={"PATH=/bin:/usr/bin","TERM=vt100",NULL};
    execve(args[0],args,env);
    return fail("root exec");
}
static int exe_identity(dev_t device)
{
    char proc[256],path[300];live_mount(2,proc);
    (void)snprintf(path,sizeof(path),"%s/1/exe",proc);
    struct stat sb;int fd=checked_file(path,st.hashes.pid1,64ULL*1024*1024,&sb,1);
    if(fd<0) return -1;
    int r=sb.st_dev==device?0:invalid("PID1 executable filesystem identity");
    if(checked_close(fd)<0) r=-1;
    return r;
}
static int root_identity(int root_executable)
{
    struct stat sb;struct statfs fs;
    if(stat("/",&sb)<0||statfs("/",&fs)<0) return fail("root filesystem stat");
    if(sb.st_dev!=st.root_dev||(unsigned long)fs.f_type!=EXT4_MAGIC) return invalid("root filesystem identity");
    if(mount_table(0)<0||mount_identity("/","ext4",7,st.loop_number,1)<0||(root_executable&&exe_identity((dev_t)st.root_dev)<0)||checked_hash("/.ram-return/bin/pid1",st.hashes.pid1,0)<0||checked_hash("/.ram-return/bin/busybox",BB_SHA,0)<0||fd_guard()<0) return -1;
    char cache[256];live_mount(0,cache);
    if(mount_identity(cache,"ext4",major(st.cache_dev),minor(st.cache_dev),1)<0) return -1;
    int loop=loop_fd(1);
    return loop<0?-1:checked_close(loop);
}
static int mount_children_guard(void)
{
    return mount_table(0);
}
static int island_executable(void)
{
    const char *base=island_entered?"/":island();
    struct stat sb;struct statfs fs;
    if(stat(base,&sb)<0||statfs(base,&fs)<0) return fail("return island identity stat");
    if(!S_ISDIR(sb.st_mode)||sb.st_uid||sb.st_gid||
       (uint64_t)sb.st_dev!=st.mounts[ISLAND_MOUNT].device||
       (unsigned long)fs.f_type!=TMPFS_MAGIC) return invalid("return island filesystem identity");
    return exe_identity(sb.st_dev);
}
static int begin_return(void)
{
    if(!state_verified||root_identity(1)<0||process_guard()<0||fd_guard()<0||mount_children_guard()<0) return -1;
    st.phase=RETURN;
    if(state_save()<0) return -1;
    char *const args[]={"/.ram-return/bin/pid1","return",NULL};char *const env[]={"PATH=/bin:/usr/bin","TERM=vt100",NULL};
    execve(args[0],args,env);
    return fail("island exec");
}
static int retry_root_exec(void)
{
    if(st.phase!=ROOT||st.forward!=63||st.backward||st.pivoted||st.root_unmounted||st.loop_detached||st.cache_unmounted) return invalid("root retry state");
    if(!root_entered) {
        if(!switch_moved) {
            if(chdir("/newroot")<0) return fail("retry switch cwd");
            if(mount(".","/",NULL,MS_MOVE,NULL)<0) return fail("retry switch move");
            switch_moved=1;
        }
        if(chroot(".")<0) return fail("retry switch chroot");
        root_entered=1;
    }
    if(chdir("/")<0||root_identity(0)<0||checked_hash("/bin/pid1",st.hashes.pid1,0)<0||process_guard()<0||fd_guard()<0) return fail("retry root checks");
    char *const args[]={"/bin/pid1","root",NULL};char *const env[]={"PATH=/bin:/usr/bin","TERM=vt100",NULL};
    execve(args[0],args,env);
    return fail("retry root exec");
}
static int finish_return(void)
{
    if(!state_verified||(st.phase!=RETURN&&st.phase!=RAM)) return invalid("return state unverified");
    if(pivot_chroot_needed) {
        if(chroot(".")<0||chdir("/")<0) return fail("retry pivot chroot/cwd");
        pivot_chroot_needed=0;
    }
    if(island_executable()<0||mount_children_guard()<0||process_guard()<0||fd_guard()<0) return -1;
    if(!st.pivoted&&root_identity(0)<0) return -1;
    if(!st.pivoted) {
        if(process_guard()<0||fd_guard()<0||mount_children_guard()<0) return -1;
        for(size_t i=0;i<6;i++) {
            if(st.backward&(1u<<i)) continue;
            char src[256],dst[256];live_mount(i,src);
            (void)snprintf(dst,sizeof(dst),"%s/%s",island(),i==0?"backing-cache":names[i]);
            if(mount(src,dst,NULL,MS_MOVE,NULL)<0) return fail("return mount move");
            st.backward|=1u<<i;
            if(mount_children_guard()<0||state_save()<0) return -1;
        }
        int fd=loop_fd(1);
        if(fd<0||checked_close(fd)<0||process_guard()<0||fd_guard()<0) return -1;
        if(chdir(island())<0) return fail("return chdir");
        if(syscall(SYS_pivot_root,".","old-root")<0) return fail("pivot_root");
        st.pivoted=1;island_entered=1;pivot_chroot_needed=1;
        if(chroot(".")<0) return fail("return chroot");
        if(chdir("/")<0) return fail("return cwd");
        pivot_chroot_needed=0;
        if(mount_children_guard()<0||state_save()<0) return -1;
    }
    if(!st.root_unmounted) {
        if(mount_children_guard()<0||process_guard()<0||fd_guard()<0) return -1;
        if(mount_identity("/old-root","ext4",7,st.loop_number,1)<0) return -1;
        if(umount2("/old-root",0)<0) return fail("old-root normal umount");
        st.root_unmounted=1;
        if(mount_children_guard()<0||state_save()<0) return -1;
    }
    if(!st.loop_detached) {
        int loop=loop_fd(1);
        if(loop<0) return -1;
        int r=ioctl(loop,LOOP_CLR_FD)<0?fail("owned loop detach"):0;
        if(!r) st.loop_detached=1;
        if(checked_close(loop)<0) r=-1;
        if(r<0) return -1;
        if(state_save()<0) return -1;
    }
    int loop=loop_fd(0);
    if(loop<0||checked_close(loop)<0) return -1;
    if(!st.cache_unmounted) {
        if(mount_children_guard()<0||mount_identity("/backing-cache","ext4",major(st.cache_dev),minor(st.cache_dev),1)<0||process_guard()<0||fd_guard()<0) return -1;
        if(umount2("/backing-cache",0)<0) return fail("cache normal umount");
        st.cache_unmounted=1;st.phase=RAM;
        if(state_save()<0) return -1;
    }
    return island_executable()<0||mount_children_guard()<0||process_guard()<0||fd_guard()<0?-1:0;
}
static int resume_return(void)
{
    if(!state_verified||(st.phase!=RETURN&&st.phase!=RAM)) return invalid("resume return state unverified");
    if(!st.pivoted&&!st.backward&&island_executable()<0) {
        /* Failed exec still maps ext4: repeat every original check before exec. */
        if(st.phase!=RETURN||st.root_unmounted||st.loop_detached||st.cache_unmounted||
           root_identity(1)<0||process_guard()<0||fd_guard()<0||mount_children_guard()<0)
            return invalid("retry island exec checks");
        struct stat sb;struct statfs fs;
        if(stat(island(),&sb)<0||statfs(island(),&fs)<0) return fail("retry island stat");
        if((uint64_t)sb.st_dev!=st.mounts[ISLAND_MOUNT].device||
           (unsigned long)fs.f_type!=TMPFS_MAGIC) return invalid("retry island filesystem");
        /* The first transition may have failed before/while persisting state. */
        if(state_save()<0) return -1;
        char *const args[]={"/.ram-return/bin/pid1","return",NULL};
        char *const env[]={"PATH=/bin:/usr/bin","TERM=vt100",NULL};
        execve(args[0],args,env);
        return fail("retry island exec");
    }
    return finish_return();
}
static void status(void)
{
    dprintf(1,"PID1_STATUS phase=%u loop=%u owned=%u forward=%u backward=%u pivot=%u old_unmounted=%u loop_detached=%u cache_unmounted=%u\n",st.phase,st.loop_number,st.loop_owned,st.forward,st.backward,st.pivoted,st.root_unmounted,st.loop_detached,st.cache_unmounted);
    if(error_step[0]) dprintf(1,"PID1_RESCUE first=%s errno=%d\n",error_step,error_number);
    for(size_t i=0;i<6;i++) { char path[256];dprintf(1,"MOUNT_PATH %s\n",live_mount(i,path)); }
}
static const char *busybox_path(char path[256])
{
    if(island_entered) return "/bin/busybox";
    if(root_entered||bootstrap_island) { (void)snprintf(path,256,"%s/bin/busybox",island());return path; }
    return "/bin/busybox";
}
static int run_child(const char *program, int shell)
{
    if(owned_child) return invalid("session already active");
    int ready[2];
    if(pipe2(ready,O_CLOEXEC)<0) return fail("session pipe");
    int permit[2];
    if(pipe2(permit,O_CLOEXEC)<0) { fail("session permit pipe");checked_close(ready[0]);checked_close(ready[1]);return -1; }
    pid_t pid=fork();
    if(pid<0) { fail("console fork");checked_close(ready[0]);checked_close(ready[1]);checked_close(permit[0]);checked_close(permit[1]);return -1; }
    if(!pid) {
        if(close(ready[0])<0||close(permit[1])<0) _exit(126);
        struct sigaction def={.sa_handler=SIG_DFL};sigemptyset(&def.sa_mask);
        if(sigaction(SIGCHLD,&def,NULL)<0||sigaction(SIGTERM,&def,NULL)<0||sigaction(SIGINT,&def,NULL)<0||sigaction(SIGQUIT,&def,NULL)<0) _exit(126);
        if(setsid()<0||ioctl(0,TIOCSCTTY,1)<0) _exit(126);
        if(exact_write(ready[1],"R",1)<0||close(ready[1])<0) _exit(126);
        char granted=0;
        if(exact_read(permit[0],&granted,1)<0||granted!='C'||close(permit[0])<0) _exit(126);
        char *const args_shell[]={(char *)program,"sh","-i",NULL};
        char *const args_test[]={(char *)program,NULL};
        char *const env[]={"PATH=/bin:/usr/bin","TERM=vt100","HOME=/","PS1=pid1-rescue# ",NULL};
        execve(program,shell?args_shell:args_test,env);
        _exit(127);
    }
    owned_child=pid;
    char proc[256];live_mount(2,proc);
    struct process p;
    int initial=checked_close(ready[1]);
    if(checked_close(permit[0])<0) initial=-1;
    if(initial<0) { checked_close(ready[0]);checked_close(permit[1]);return -1; }
    if(process_stat(proc,pid,&p)<0) { checked_close(ready[0]);checked_close(permit[1]);return -1; }
    if(p.parent!=1||!p.start) { invalid("owned child ancestry");checked_close(ready[0]);checked_close(permit[1]);return -1; }
    owned_start=p.start;
    struct pollfd handshake={.fd=ready[0],.events=POLLIN};
    int handshake_result;
    do { handshake_result=poll(&handshake,1,5000); } while(handshake_result<0&&errno==EINTR);
    char received=0;int r=0;
    if(handshake_result!=1||!(handshake.revents&POLLIN)||exact_read(ready[0],&received,1)<0||received!='R') r=invalid("child session handshake");
    if(checked_close(ready[0])<0) r=-1;
    if(r<0) { checked_close(permit[1]);return -1; }
    if(process_stat(proc,pid,&p)<0) { checked_close(permit[1]);return -1; }
    if(p.parent!=1||p.start!=owned_start||p.group!=pid||p.session!=pid) { invalid("child session identity");checked_close(permit[1]);return -1; }
    r=exact_write(permit[1],"C",1);
    if(checked_close(permit[1])<0) r=-1;
    if(r<0) return -1;
    int status_value;
    for(;;) {
        pid_t reaped=waitpid(-1,&status_value,0);
        if(reaped<0&&errno==EINTR) continue;
        if(reaped<=0) return fail("owned session wait");
        if(reaped==pid) break;
        dprintf(1,"ADOPTED_CHILD_REAPED pid=%ld status=%d\n",(long)reaped,status_value);
    }
    dprintf(1,"OWNED_SESSION_REAPED pid=%ld start=%llu status=%d\n",(long)pid,owned_start,status_value);
    owned_child=0;owned_start=0;
    if(reap()<0) return -1;
    if(!shell) {
        if(!WIFEXITED(status_value)||WEXITSTATUS(status_value)) return invalid("software test failed");
        dprintf(1,"SOFTWARE_TEST_PASSED path=%s exit=0\n",program);
    }
    return 0;
}
static int stop_owned(void)
{
    if(!owned_child||!owned_start) return invalid("no identified owned session");
    char proc[256];live_mount(2,proc);struct process p;
    if(process_stat(proc,owned_child,&p)<0) return -1;
    if(p.parent!=1||p.start!=owned_start||p.group!=owned_child||p.session!=owned_child) return invalid("stop session identity");
    if(kill(-owned_child,SIGTERM)<0) return fail("owned session SIGTERM");
    for(int attempt=0;attempt<50;attempt++) {
        if(reap()<0) return -1;
        if(!owned_child) return 0;
        if(poll(NULL,0,100)<0&&errno!=EINTR) return fail("owned stop wait");
    }
    if(process_stat(proc,owned_child,&p)<0) return -1;
    if(p.parent!=1||p.start!=owned_start||p.group!=owned_child||p.session!=owned_child) return invalid("stop recheck identity");
    if(kill(-owned_child,SIGKILL)<0) return fail("owned session SIGKILL");
    for(int attempt=0;attempt<50;attempt++) {
        if(reap()<0) return -1;
        if(!owned_child) return 0;
        if(poll(NULL,0,100)<0&&errno!=EINTR) return fail("owned stop kill wait");
    }
    return invalid("owned session did not reap; return blocked");
}
static void on_child(int sig) { (void)sig;child_pending=1; }
static void console_loop(int rescue)
{
    for(;;) {
        if(child_pending&&reap()<0) rescue=1;
        status();
        dprintf(1,"PID1_%s commands: status shell codec pty stop return resume\n",rescue?"RESCUE":"CONSOLE");
        char line[128];size_t used=0;
        while(used<sizeof(line)-1) {
            if(child_pending&&reap()<0) rescue=1;
            char c;ssize_t n=read(0,&c,1);
            if(n<0&&errno==EINTR) { if(reap()<0) rescue=1;continue; }
            if(n<=0) { sleep(1);continue; }
            if(c=='\n'||c=='\r') break;
            line[used++]=c;
        }
        line[used]=0;
        if(!strcmp(line,"status")||!used) continue;
        if(!strcmp(line,"stop")) {
            if(stop_owned()<0) rescue=1;
        } else if(!strcmp(line,"shell")) {
            char path[256];const char *bb=busybox_path(path);
            if(checked_hash(bb,BB_SHA,0)<0||run_child(bb,1)<0) rescue=1;
        } else if((!strcmp(line,"codec")||!strcmp(line,"pty"))&&st.phase==ROOT&&!rescue) {
            const char *path=!strcmp(line,"codec")?"/usr/bin/codec-test":"/usr/bin/pty-test";
            const char *hash=!strcmp(line,"codec")?CODEC_SHA:PTY_SHA;
            if(checked_hash(path,hash,0)<0||run_child(path,0)<0) rescue=1;
        } else if(!strcmp(line,"return")&&st.phase==ROOT) {
            if(begin_return()<0) rescue=1;
        } else if(!strcmp(line,"resume")&&(st.phase==RETURN||(st.phase==RAM&&rescue))) {
            if(resume_return()<0) rescue=1;
            else { rescue=0;dprintf(1,"LINUX_PID1_RAM_READY_NO_RESET\n"); }
        } else if(!strcmp(line,"resume")&&st.phase==ROOT&&rescue) {
            if(retry_root_exec()<0) rescue=1;
        } else dprintf(1,"Command unavailable in this phase; no reset was issued.\n");
    }
}
static int console_setup(void)
{
    int fd=open("/dev/console",O_RDWR|O_NOFOLLOW|O_CLOEXEC|O_NONBLOCK);
    if(fd<0) return fail("console open");
    struct stat sb;
    if(fstat(fd,&sb)<0) { fail("console stat");checked_close(fd);return -1; }
    if(!S_ISCHR(sb.st_mode)||sb.st_rdev!=makedev(5,1)) { invalid("console device");checked_close(fd);return -1; }
    if(fcntl(fd,F_SETFL,0)<0) { fail("console blocking");checked_close(fd);return -1; }
    for(int i=0;i<3;i++) {
        if(dup2(fd,i)<0) { fail("console dup2");checked_close(fd);return -1; }
        if(fcntl(i,F_SETFD,0)<0) { fail("console FD inherit");if(fd>2) checked_close(fd);return -1; }
    }
    return fd>2?checked_close(fd):0;
}
int main(int argc, char **argv)
{
    if(getpid()!=1) { dprintf(2,"Only the real Linux PID1 may run this program.\n");return 2; }
    struct sigaction action={.sa_handler=on_child,.sa_flags=SA_NOCLDSTOP};sigemptyset(&action.sa_mask);
    if(sigaction(SIGCHLD,&action,NULL)<0) fail("SIGCHLD install");
    if(getuid()!=0) invalid("PID1 requires root");
    int mode=argc==1?BOOTSTRAP:(argc==2&&!strcmp(argv[1],"bootstrap")?BOOTSTRAP:(argc==2&&!strcmp(argv[1],"root")?ROOT:(argc==2&&!strcmp(argv[1],"return")?RETURN:0)));
    if(!mode) invalid("CLI mode");
    if(console_setup()<0) { /* Embedded /dev/console or inherited console stays usable. */ }
    if(error_step[0]) console_loop(1);
    if(mode==BOOTSTRAP) { if(bootstrap()<0) console_loop(1); }
    else {
        root_entered=1;
        if(state_read()<0) console_loop(1);
        if(mode==ROOT) {
            if(st.phase!=ROOT||st.backward||st.pivoted||st.root_unmounted||st.loop_detached||st.cache_unmounted||root_identity(1)<0) { invalid("root phase state");console_loop(1); }
            dprintf(1,"LINUX_PID1_ROOT_READY\n");console_loop(0);
        } else {
            struct stat sb;
            if(st.phase!=RETURN||st.backward||st.pivoted||st.root_unmounted||st.loop_detached||st.cache_unmounted||stat(island(),&sb)<0||exe_identity(sb.st_dev)<0||root_identity(0)<0||finish_return()<0) { invalid("return phase state");console_loop(1); }
            dprintf(1,"LINUX_PID1_RAM_READY_NO_RESET\n");console_loop(0);
        }
    }
    fail("unexpected PID1 continuation");console_loop(1);
    return 1; /* Unreachable: PID1 console_loop never returns. */
}
