#include "video_frame.hpp"
#include <im2d.h>
#include <chrono>
#include <cstring>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <vector>
using Clock=std::chrono::steady_clock;
double ms(Clock::time_point t){return std::chrono::duration<double,std::milli>(Clock::now()-t).count();}
struct Buffer {
    std::vector<unsigned char> bytes;
    rga_buffer_handle_t handle=0;
    explicit Buffer(size_t size):bytes(size){handle=importbuffer_virtualaddr(bytes.data(),static_cast<int>(size));if(!handle)throw std::runtime_error("RGA virtualaddr import failed");}
    ~Buffer(){if(handle)releasebuffer_handle(handle);}
};
void check(IM_STATUS status){if(status!=IM_STATUS_SUCCESS && status!=IM_STATUS_NOERROR)throw std::runtime_error(imStrError(status));}
void save(const std::string& p,const cv::Mat& im){std::ofstream f(p,std::ios::binary);for(int row=0;row<im.rows;++row)f.write(reinterpret_cast<const char*>(im.ptr(row)),im.cols*3);if(!f)throw std::runtime_error("save failed");}
int main(int argc,char**argv){try{
    int count=argc>1?std::stoi(argv[1]):30;int ow=argc>2?std::stoi(argv[2]):960;
    std::string matrix=argc>3?argv[3]:"bt601",range=argc>4?argv[4]:"full";
    std::string prefix=argc>5?argv[5]:"rga-compare";
    if(count<1||count>1000||(ow!=960&&ow!=2112)|| (matrix!="bt601"&&matrix!="bt709") ||(range!="full"&&range!="limited"))throw std::runtime_error("Usage: count width(960|2112) bt601|bt709 full|limited output-prefix [packed-NV12-file]");
    constexpr int w=2112,h=1568,ys=2128,us=2144;const int oh=h*ow/w;
    std::vector<unsigned char> y(ys*h,201),uv(us*h/2,202);
    if(argc>6){std::ifstream f(argv[6],std::ios::binary);for(int r=0;r<h;++r)f.read(reinterpret_cast<char*>(y.data()+r*ys),w);for(int r=0;r<h/2;++r)f.read(reinterpret_cast<char*>(uv.data()+r*us),w);if(!f)throw std::runtime_error("packed NV12 input must contain full active rows");}
    else{unsigned seed=17;for(int r=0;r<h;++r)for(int c=0;c<w;++c){seed=seed*1664525u+1013904223u;y[r*ys+c]=static_cast<unsigned char>((c/8+r/7+(seed>>29))&255);}for(int r=0;r<h/2;++r)for(int c=0;c<w;c+=2){uv[r*us+c]=static_cast<unsigned char>(32+(r/5)%192);uv[r*us+c+1]=static_cast<unsigned char>(32+(c/7)%192);}}
    rtctrl_camera_frame frame{};frame.format={w,h,RTCTRL_PIXEL_NV12,0,2,0,range=="full"?RTCTRL_RANGE_FULL:RTCTRL_RANGE_LIMITED,0,matrix=="bt601"?RTCTRL_YCBCR_BT601:RTCTRL_YCBCR_BT709};
    frame.planes[0].data=y.data();frame.planes[0].size=y.size();frame.planes[0].stride=ys;frame.planes[1].data=uv.data();frame.planes[1].size=uv.size();frame.planes[1].stride=us;
    auto init=Clock::now();Buffer staging(w*h*3/2),dest(ow*oh*3);
    auto src=wrapbuffer_handle(staging.handle,w,h,RK_FORMAT_YCbCr_420_SP);
    auto dst=wrapbuffer_handle(dest.handle,ow,oh,RK_FORMAT_BGR_888);
    // No two-FD contiguity assumption: copy active rows from separate planes.
    auto stage=[&]{for(int r=0;r<h;++r)std::memcpy(staging.bytes.data()+r*w,y.data()+r*ys,w);for(int r=0;r<h/2;++r)std::memcpy(staging.bytes.data()+w*h+r*w,uv.data()+r*us,w);};
    if(matrix=="bt601")dst.color_space_mode=range=="full"?IM_YUV_TO_RGB_BT601_FULL:IM_YUV_TO_RGB_BT601_LIMIT;
    else if(range=="limited")dst.color_space_mode=IM_YUV_TO_RGB_BT709_LIMIT;
    else{src.color_space_mode=IM_YUV_BT709_FULL_RANGE;dst.color_space_mode=IM_RGB_FULL;}
    std::cout<<"header="<<RGA_API_FULL_VERSION<<" init_ms="<<ms(init)<<" width="<<ow<<" height="<<oh<<" matrix="<<matrix<<" range="<<range<<" interpolation=IM_INTERP_DEFAULT (NOT nearest guarantee)\n";
    double scalar_ms=0,stage_ms=0,rga_ms=0;cv::Mat reference;
    auto scalar=[&]{auto t=Clock::now();reference=rtctrl::face::video_frame_bgr(frame,ow);scalar_ms+=ms(t);};
    auto hardware=[&]{auto t=Clock::now();stage();stage_ms+=ms(t);t=Clock::now();check(imresize(src,dst,0,0,IM_INTERP_DEFAULT,1));rga_ms+=ms(t);};
    for(int i=0;i<count;++i){if(i%2){hardware();scalar();}else{scalar();hardware();}}
    cv::Mat result(oh,ow,CV_8UC3,dest.bytes.data());size_t different=0,pixels=0;int maxdiff=0;double sum=0;
    for(int r=0;r<oh;++r)for(int c=0;c<ow;++c){bool changed=false;for(int k=0;k<3;++k){int delta=std::abs(int(reference.at<cv::Vec3b>(r,c)[k])-int(result.at<cv::Vec3b>(r,c)[k]));sum+=delta;maxdiff=std::max(maxdiff,delta);different+=delta!=0;changed|=delta!=0;}pixels+=changed;}
    save(prefix+"-scalar.bgr",reference);save(prefix+"-rga.bgr",result);
    std::cout<<"count="<<count<<" scalar_mean_ms="<<scalar_ms/count<<" stage_mean_ms="<<stage_ms/count<<" rga_sync_mean_ms="<<rga_ms/count<<" stage_plus_rga_mean_ms="<<(stage_ms+rga_ms)/count<<" max_channel_delta="<<maxdiff<<" mean_channel_delta="<<sum/(ow*oh*3)<<" changed_channels="<<different<<" changed_pixels="<<pixels<<" pixel_count="<<ow*oh<<" bitexact="<<(maxdiff==0)<<"\n";
    return 0;
}catch(const std::exception&e){std::cerr<<e.what()<<"\n";return 1;}}
