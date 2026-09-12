from pathlib import Path
import shutil, subprocess
sdk=Path('/home/sx/projects/atk_dlrv1126b_linux6.1_sdk')
base=Path('/home/sx/projects/rtctrl-platform/work/mpp-reuse')
host=Path('/mnt/c/Users/lenovo/Documents/Codex/2026-09-11/you/work')
sysroot=base/'sysroot'
sysroot.mkdir(parents=True,exist_ok=True)
packages=[host/'libglib-dev-arm64.deb']
for directory, pattern in [('gstreamer','libgstreamer1.0-dev_*.deb'),('gst-plugins-base1.0','libgstreamer-plugins-base1.0-dev_*.deb'),('rga2','librga-dev_*.deb'),('mpp','librockchip-mpp-dev_*.deb')]:
    packages.extend((sdk/'debian/packages/arm64'/directory).glob(pattern))
for package in packages:
    subprocess.run(['dpkg-deb','-x',str(package),str(sysroot)],check=True)
subprocess.run(['tar','-xf',str(host/'preview-build-libs.tar'),'-C',str(sysroot)],check=True)
shutil.copytree(sdk/'external/mpp/inc',sysroot/'usr/include/rockchip',dirs_exist_ok=True)
shutil.copytree(sdk/'external/linux-rga/include',sysroot/'usr/include/rga',dirs_exist_ok=True)
source=base/'source'
shutil.copytree(sdk/'external/gstreamer-rockchip/gst/rockchipmpp',source,dirs_exist_ok=True)
p=source/'gstmppenc.c'
s=p.read_text()
old='gst_mpp_allocator_set_cacheable (self->allocator, FALSE);'
assert s.count(old)==1
s=s.replace(old,'gst_mpp_allocator_set_cacheable (self->allocator,\n      g_strcmp0 (g_getenv ("RTCTRL_MPP_REUSE"), "1") == 0);')
p.write_text(s)
(source/'config.h').write_text('''#define VERSION "1.14.4"
#define GST_LICENSE "LGPL"
#define PACKAGE "gst-rockchip"
#define PACKAGE_VERSION "1.14.4"
#define GST_PACKAGE_NAME "RTCTRL isolated buffer reuse test"
#define GST_PACKAGE_ORIGIN "local SDK test"
#define HAVE_RGA 1
''')
compiler=sdk/'prebuilts/gcc/linux-x86/aarch64/gcc-arm-10.3-2021.07-x86_64-aarch64-none-linux-gnu/bin/aarch64-none-linux-gnu-gcc'
files=['gstmpp','gstmppallocator','gstmppdec','gstmppjpegdec','gstmppvideodec','gstmppenc','gstmppjpegenc','gstmpph264enc','gstmpph265enc','gstmppvp8enc']
includes=[source,sdk/'external/mpp/inc',sdk/'external/linux-rga/include',sdk/'external/linux-rga/im2d_api',sysroot/'usr/include',sysroot/'usr/include/gstreamer-1.0',sysroot/'usr/include/glib-2.0',sysroot/'usr/lib/aarch64-linux-gnu/glib-2.0/include']
out=base/'plugin';out.mkdir(exist_ok=True)
cmd=[str(compiler),'-shared','-fPIC','-O2','-g','-fvisibility=hidden','-fno-omit-frame-pointer','-fno-strict-aliasing','-DHAVE_CONFIG_H','-DUNUSED=__attribute__((unused))']
cmd+=['-I'+str(p) for p in includes]
cmd += [str(source/(name+'.c')) for name in files]
cmd+=['-L'+str(sysroot/'usr/lib'),'-Wl,-rpath-link,'+str(sysroot/'usr/lib'),'-Wl,-rpath-link,'+str(sysroot/'lib')]
cmd+=['-l'+lib for lib in ['gstvideo-1.0','gstallocators-1.0','gstpbutils-1.0','gstbase-1.0','gstreamer-1.0','gobject-2.0','glib-2.0','rockchip_mpp','rga']]
cmd+=['-o',str(out/'libgstrockchipmpp.so')]
subprocess.run(cmd,check=True)
print(out/'libgstrockchipmpp.so')
