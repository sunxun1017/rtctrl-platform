#include "../../apps/face_recognition/detector_resize.cpp"
namespace rtctrl::face { cv::Mat scalar_letterbox(const cv::Mat&, int, int); }
#include <opencv2/core.hpp>
#include <opencv2/imgproc.hpp>
#include <algorithm>
#include <chrono>
#include <cmath>
#include <iostream>
#include <stdexcept>
#include <time.h>
static double cpu(){timespec t{};clock_gettime(CLOCK_PROCESS_CPUTIME_ID,&t);return t.tv_sec*1e6+t.tv_nsec/1e3;}
static cv::Mat original(const cv::Mat& s){float scale=std::min(320.f/s.cols,320.f/s.rows);int w=std::max(1,int(std::round(s.cols*scale))),h=std::max(1,int(std::round(s.rows*scale)));cv::Mat out(320,320,CV_8UC3,cv::Scalar(0,0,0)), resized;cv::resize(s,resized,{w,h});resized.copyTo(out(cv::Rect((320-w)/2,(320-h)/2,w,h)));return out;}
// Only 960-wide landscape BGR8: horizontal INTER_LINEAR selects x=3*dx+1.
// Preserve OpenCV 3.4.5's two-stage vertical fixed-point truncation/rounding.
static cv::Mat candidate(const cv::Mat& s) {
    return rtctrl::face::detector_letterbox(s,320,std::max(1,int(std::round(s.rows*(320.f/s.cols)))));
}

int main(int argc,char**argv){try{
 int n=argc>1?std::stoi(argv[1]):100;if(n<1||n>10000)throw std::runtime_error("iterations");cv::setNumThreads(1);std::cout<<cv::getBuildInformation()<<"\noptimized="<<cv::useOptimized()<<" threads="<<cv::getNumThreads()<<'\n';
 cv::RNG rng(0x918273);
 for(int h:{1,2,237,479,711,712,713,720,960})for(int pattern=0;pattern<12;pattern++){
  cv::Mat storage(h,967,CV_8UC3);if(pattern<3)storage.setTo(cv::Scalar(pattern*127,255-pattern*127,pattern));else rng.fill(storage,cv::RNG::UNIFORM,0,256);
  auto input=storage(cv::Rect(3,0,960,h));auto a=original(input),b=candidate(input);double e=cv::norm(a,b,cv::NORM_INF);
  if(e!=0){std::cout<<"FAIL height="<<h<<" pattern="<<pattern<<" max_error="<<e<<'\n';return 3;}
 }
 std::cout<<"validation cases=108 full_letterbox=1 all_equal=1 noncontinuous_input=1\n";
 cv::Mat storage(712,967,CV_8UC3);rng.fill(storage,cv::RNG::UNIFORM,0,256);auto input=storage(cv::Rect(3,0,960,712));
 for(int baseline=0;baseline<2;++baseline)for(int round=0;round<4;round++)for(int slot=0;slot<2;slot++){
 bool fast=(round%2==0)?slot==1:slot==0;double c=cpu();auto t=std::chrono::steady_clock::now();cv::Mat result;
 for(int i=0;i<n;i++)result=fast?candidate(input):(baseline ? rtctrl::face::scalar_letterbox(input,320,237) : original(input));
 double wall=std::chrono::duration<double,std::micro>(std::chrono::steady_clock::now()-t).count()/n;double used=(cpu()-c)/n;
 if(cv::norm(result,original(input),cv::NORM_INF)!=0)throw std::runtime_error("timed mismatch");
 std::cout<<"sample baseline="<<(baseline?"scalar":"opencv")<<" round="<<round<<" fast="<<fast<<" wall_us="<<wall<<" process_cpu_us="<<used<<" equal=1\n";
 }
}catch(const std::exception&e){std::cerr<<e.what()<<'\n';return 1;}}
