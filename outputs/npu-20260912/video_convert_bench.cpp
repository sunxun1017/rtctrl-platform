#include "video_frame.hpp"
#include <chrono>
#include <iostream>
#include <vector>
#include <string>
namespace rtctrl::face { cv::Mat video_frame_bgr_scalar(const rtctrl_camera_frame&,int,VideoColor); }
int main(int argc,char**argv) {
    using namespace rtctrl::face;
    int count=argc>2?std::stoi(argv[2]):100;
    std::string mode=argc>1?argv[1]:"both";
    rtctrl_camera_frame f{};
    f.format={2112,1568,RTCTRL_PIXEL_NV12,0,1,0,RTCTRL_RANGE_FULL,0,RTCTRL_YCBCR_BT601};
    std::vector<unsigned char> bytes(2112*1568*3/2);
    unsigned seed=17; for(auto& b:bytes){seed=seed*1664525u+1013904223u;b=seed>>24;}
    f.planes[0].data=bytes.data();f.planes[0].size=bytes.size();f.planes[0].stride=2112;
    auto old=video_frame_bgr_scalar(f,960,{});auto fresh=video_frame_bgr(f,960,{});
    std::cout<<"max_channel_delta="<<cv::norm(old,fresh,cv::NORM_INF)<<"\n";
    for (const std::string name:{"scalar","lut"}) {
        if(mode!="both"&&mode!=name)continue;
        auto convert=name=="scalar"?video_frame_bgr_scalar:video_frame_bgr;
        double checksum=0;
        for(int i=0;i<5;++i)convert(f,960,{});
        auto start=std::chrono::steady_clock::now();
        for(int i=0;i<count;++i) {auto b=convert(f,960,{});checksum+=b.at<cv::Vec3b>(i%b.rows,i%b.cols)[0];}
        auto ms=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-start).count();
        std::cout<<name<<" frames="<<count<<" total_ms="<<ms<<" mean_ms="<<ms/count<<" checksum="<<checksum<<"\n";
    }
}
