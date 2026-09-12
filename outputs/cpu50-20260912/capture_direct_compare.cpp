#include "rga_frame.hpp"
#include "rtctrl/adapters/v4l2/capture.h"
#include <im2d.h>
#include <linux/videodev2.h>
#include <sys/ioctl.h>
#include <fcntl.h>
#include <unistd.h>
#include <time.h>
#include <cerrno>
#include <chrono>
#include <cstring>
#include <iostream>
#include <map>
#include <vector>
#include <limits>
#include <stdexcept>
static void need(bool b,const char* s){if(!b)throw std::runtime_error(s);}
static double cpu(){timespec t{};need(clock_gettime(CLOCK_THREAD_CPUTIME_ID,&t)==0,"clock");return t.tv_sec*1000.0+t.tv_nsec/1e6;}
static double wall(){return std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now().time_since_epoch()).count();}
static int ctl(int fd,unsigned long cmd,void*p){int r;do{r=ioctl(fd,cmd,p);}while(r<0&&errno==EINTR);return r;}
static void show(const char* label,const v4l2_format& f){
 const auto&p=f.fmt.pix_mp;char code[5]={char(p.pixelformat),char(p.pixelformat>>8),char(p.pixelformat>>16),char(p.pixelformat>>24),0};
 std::cout<<label<<" width="<<p.width<<" height="<<p.height<<" fourcc="<<code<<" planes="<<unsigned(p.num_planes);
 for(unsigned i=0;i<p.num_planes;++i)std::cout<<" stride"<<i<<"="<<p.plane_fmt[i].bytesperline<<" allocation"<<i<<"="<<p.plane_fmt[i].sizeimage;
 std::cout<<std::endl;
}
struct Restore{
 int fd=-1;v4l2_format saved{};bool valid=false;bool restored=false;
 explicit Restore(const char* path){
  fd=open(path,O_RDWR|O_CLOEXEC);need(fd>=0,"open original format");
  saved.type=V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE;
  if(ctl(fd,VIDIOC_G_FMT,&saved)<0){close(fd);fd=-1;throw std::runtime_error("original G_FMT");}
  valid=true;show("original",saved);
 }
 bool finish(){
  if(restored)return true;restored=true;bool ok=true;
  if(valid){auto copy=saved;ok=ctl(fd,VIDIOC_S_FMT,&copy)==0;
   v4l2_format actual{};actual.type=saved.type;
   if(ctl(fd,VIDIOC_G_FMT,&actual)<0)ok=false;
   else{show("restored_actual",actual);auto&a=actual.fmt.pix_mp;auto&b=saved.fmt.pix_mp;
    if(a.width!=b.width||a.height!=b.height||a.pixelformat!=b.pixelformat||a.num_planes!=b.num_planes)ok=false;
    for(unsigned i=0;i<b.num_planes;++i)if(a.plane_fmt[i].bytesperline!=b.plane_fmt[i].bytesperline||a.plane_fmt[i].sizeimage!=b.plane_fmt[i].sizeimage)ok=false;
   }
  }
  std::cout<<"restore_ok="<<ok<<std::endl;return ok;
 }
 ~Restore(){if(fd>=0){finish();close(fd);}}
};
struct Camera{rtctrl_camera*p=nullptr;~Camera(){if(p){int r=rtctrl_camera_close(p);std::cout<<"camera_close_rc="<<r<<std::endl;}}};
struct Lease{rtctrl_camera*c;rtctrl_camera_frame f{};bool held=false;
 ~Lease(){if(held)rtctrl_camera_release(c,f.token);}
 void release(){int r=rtctrl_camera_release(c,f.token);held=false;need(r==0,"frame release");}
};
struct Direct{
 std::map<int,rga_buffer_handle_t> handles;
 std::vector<unsigned char> bytes=std::vector<unsigned char>(960*712*3);
 rga_buffer_handle_t output=0;
 ~Direct(){for(auto&p:handles)releasebuffer_handle(p.second);if(output)releasebuffer_handle(output);}
 cv::Mat convert(const rtctrl_camera_frame& f){
  auto&p=f.planes[0];
  need(f.format.pixel_format==RTCTRL_PIXEL_NV12&&f.format.plane_count==1&&f.format.width==2112&&f.format.height==1568&&!f.corrupt,"requires single plane 2112x1568 NV12");
  need(p.dmabuf_valid&&p.dmabuf_fd>=0&&p.data_offset==0,"requires borrowed DMA-BUF with zero offset");
  need(p.stride>=2112&&p.stride%16==0&&p.stride<=8192,"invalid pixel stride");
  size_t required=size_t(p.stride)*1568*3/2;
  need(p.size>=required&&p.allocation_size>=required&&p.allocation_size<=std::numeric_limits<int>::max(),"insufficient allocation/payload");
  auto it=handles.find(p.dmabuf_fd);
  if(it==handles.end()){
   auto h=importbuffer_fd(p.dmabuf_fd,static_cast<int>(p.allocation_size));need(h!=0,"source importbuffer_fd");
   try{it=handles.emplace(p.dmabuf_fd,h).first;}catch(...){releasebuffer_handle(h);throw;}
   std::cout<<"import fd="<<p.dmabuf_fd<<" plane=0 allocation="<<p.allocation_size<<" offset="<<p.data_offset<<" stride="<<p.stride<<std::endl;
  }
  if(!output){output=importbuffer_virtualaddr(bytes.data(),int(bytes.size()));need(output!=0,"destination import");}
  auto src=wrapbuffer_handle(it->second,2112,1568,RK_FORMAT_YCbCr_420_SP,p.stride,1568);
  auto dst=wrapbuffer_handle(output,960,712,RK_FORMAT_BGR_888,960,712);
  dst.color_space_mode=IM_YUV_TO_RGB_BT601_FULL;
  auto r=imresize(src,dst,0,0,IM_INTERP_DEFAULT,1);
  need(r==IM_STATUS_SUCCESS||r==IM_STATUS_NOERROR,"direct RGA imresize");
  return cv::Mat(712,960,CV_8UC3,bytes.data()).clone();
 }
};
int main(int argc,char**argv){
 if(argc!=2){std::cerr<<"usage: capture_direct_compare /dev/video31 (camera must be idle)\n";return 1;}
 int result=0;
 try{
  Restore restore(argv[1]);
  try{
   Camera camera;
   rtctrl_v4l2_config cfg{};cfg.device=argv[1];cfg.width=2112;cfg.height=1568;cfg.fourcc=V4L2_PIX_FMT_NV12;cfg.buffer_count=4;cfg.export_dmabuf=1;
   need(rtctrl_v4l2_open(&cfg,&camera.p)==0,"capture open");
   v4l2_format actual{};actual.type=V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE;need(ctl(restore.fd,VIDIOC_G_FMT,&actual)==0,"actual G_FMT");show("test_actual",actual);
   Direct direct;rtctrl::face::RgaFrameConverter stage;
   double sw=0,sc=0,dw=0,dc=0;bool equal=true;
   for(int i=0;i<50;++i){
    Lease lease{camera.p};need(rtctrl_camera_acquire(camera.p,1000,&lease.f)==0,"acquire");lease.held=true;
    double w=wall(),c=cpu();auto a=stage.convert(lease.f,960,{RTCTRL_YCBCR_BT601,RTCTRL_RANGE_FULL});double cc=cpu()-c,ww=wall()-w;
    w=wall();c=cpu();auto b=direct.convert(lease.f);double c2=cpu()-c,w2=wall()-w;
    if(i<30){lease.release();continue;}
    bool same=std::memcmp(a.data,b.data,960*712*3)==0;equal&=same;
    sw+=ww;sc+=cc;dw+=w2;dc+=c2;
    std::cout<<"sample="<<i-30<<" fd="<<lease.f.planes[0].dmabuf_fd<<" stage_wall_ms="<<ww<<" stage_cpu_ms="<<cc<<" direct_wall_ms="<<w2<<" direct_cpu_ms="<<c2<<" equal="<<same<<std::endl;
    lease.release();
   }
   std::cout<<"samples=20 all_equal="<<equal<<" stage_wall_mean_ms="<<sw/20<<" stage_cpu_mean_ms="<<sc/20<<" direct_wall_mean_ms="<<dw/20<<" direct_cpu_mean_ms="<<dc/20<<std::endl;
   if(!equal)result=2;
  }catch(const std::exception&e){std::cerr<<"test_error="<<e.what()<<std::endl;result=1;}
  if(!restore.finish())result=3;
 }catch(const std::exception&e){std::cerr<<e.what()<<std::endl;result=1;}
 return result;
}
