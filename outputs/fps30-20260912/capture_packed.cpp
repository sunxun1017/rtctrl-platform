#include "rtctrl/adapters/v4l2/capture.h"
#include <cerrno>
#include <cstdio>
#include <cstring>
int main(int argc,char**argv){
 if(argc!=3){std::fprintf(stderr,"Usage: capture-packed device output.nv12\n");return 2;}
 rtctrl_v4l2_config cfg{};cfg.device=argv[1];cfg.buffer_count=4;rtctrl_camera* cam=nullptr;
 int rc=rtctrl_v4l2_open(&cfg,&cam);if(rc){std::fprintf(stderr,"open: %s\n",std::strerror(-rc));return 1;}
 FILE*out=nullptr;int result=1;
 for(int i=0;i<31;++i){rtctrl_camera_frame f{};rc=rtctrl_camera_acquire(cam,2000,&f);if(rc){std::fprintf(stderr,"acquire:%d\n",rc);break;}
 if(i==30){auto w=f.format.width,h=f.format.height;auto&p=f.planes[0];
 bool valid=!f.corrupt && w && h && w%2==0 && h%2==0 && f.format.pixel_format==RTCTRL_PIXEL_NV12 && (f.format.plane_count==1||f.format.plane_count==2);
 const unsigned char*y=static_cast<const unsigned char*>(p.data),*uv=nullptr;size_t us=0;
 auto plane=[](const rtctrl_frame_plane&p,size_t rows,size_t bytes){return p.data&&rows&&p.stride>=bytes&&p.size>=bytes&&(rows-1)<=(p.size-bytes)/p.stride;};
 if(valid && f.format.plane_count==1){valid=plane(p,h+h/2,w);uv=y+size_t(p.stride)*h;us=p.stride;}
 else if(valid){valid=plane(p,h,w)&&plane(f.planes[1],h/2,w);uv=static_cast<const unsigned char*>(f.planes[1].data);us=f.planes[1].stride;}
 if(valid){out=std::fopen(argv[2],"wb");valid=out!=nullptr;}
 if(valid){for(unsigned r=0;r<h;++r)valid=std::fwrite(y+size_t(r)*p.stride,1,w,out)==w&&valid;for(unsigned r=0;r<h/2;++r)valid=std::fwrite(uv+size_t(r)*us,1,w,out)==w&&valid;}
 if(out){valid=std::fclose(out)==0&&valid;out=nullptr;}
 std::printf("width=%u height=%u planes=%u strideY=%u strideUV=%zu matrix=%u range=%u sequence=%u valid=%d\n",w,h,f.format.plane_count,p.stride,us,f.format.ycbcr_encoding,f.format.quantization,f.sequence,valid);
 result=valid?0:1;
 }
 rc=rtctrl_camera_release(cam,f.token);if(rc){result=1;break;}
 }
 if(rtctrl_camera_close(cam))result=1;return result;
}
