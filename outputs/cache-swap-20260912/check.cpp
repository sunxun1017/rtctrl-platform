#include <opencv2/core.hpp>
#include <algorithm>
#include <chrono>
#include <cmath>
#include <iostream>
#include <stdexcept>
#include <time.h>
#include <vector>
namespace rtctrl::face {
cv::Mat baseline(const cv::Mat&,int,int);
cv::Mat prefetch288(const cv::Mat&,int,int);
cv::Mat prefetch576(const cv::Mat&,int,int);
}
using Fn=cv::Mat(*)(const cv::Mat&,int,int);
static double cpu(){timespec t{};if(clock_gettime(CLOCK_THREAD_CPUTIME_ID,&t))throw std::runtime_error("clock");return t.tv_sec*1e6+t.tv_nsec/1e3;}
static double wall(){return std::chrono::duration<double,std::micro>(std::chrono::steady_clock::now().time_since_epoch()).count();}
int main(int argc,char**argv){try{
#if !defined(__aarch64__) || !defined(__ARM_NEON)
 throw std::runtime_error("This benchmark requires AArch64 NEON; host fallback is not evidence");
#endif
 int n=argc>1?std::stoi(argv[1]):300;if(n<1||n>10000)throw std::runtime_error("iterations");
 cv::setNumThreads(1);cv::RNG rng(0x314159);
 Fn functions[]={rtctrl::face::baseline,rtctrl::face::prefetch288,rtctrl::face::prefetch576};
 const char* names[]={"baseline","prefetch288","prefetch576"};
 unsigned cases=0;
 for(int h:{1,2,237,479,711,712,713,720,960})for(int p=0;p<12;++p){
  cv::Mat storage(h,967,CV_8UC3);if(p<3)storage.setTo(cv::Scalar(p*127,255-p*127,p));else rng.fill(storage,cv::RNG::UNIFORM,0,256);
  auto input=storage(cv::Rect(3,0,960,h));int oh=std::max(1,int(std::round(h*(320.f/960))));
  auto reference=functions[0](input,320,oh);
  for(int k=1;k<3;++k)if(cv::norm(reference,functions[k](input,320,oh),cv::NORM_INF)!=0)throw std::runtime_error("candidate differs");
  ++cases;
 }
 std::cout<<"validation_cases="<<cases<<" all_equal=1 ROI_noncontinuous=1\n";
 // One frame and sixteen rotating frames distinguish reuse from a larger working set.
 std::vector<cv::Mat> pool;
 for(int i=0;i<16;++i){cv::Mat storage(712,967,CV_8UC3);rng.fill(storage,cv::RNG::UNIFORM,0,256);pool.push_back(storage(cv::Rect(3,0,960,712)));}
 for(int count:{1,16})for(int round=0;round<6;++round)for(int slot=0;slot<3;++slot){
  int k=(round%2)?2-slot:slot;
  for(int i=0;i<5;++i)functions[k](pool[i%count],320,237);
  double c=cpu(),w=wall();cv::Mat result;
  for(int i=0;i<n;++i)result=functions[k](pool[i%count],320,237);
  double elapsed=wall()-w,used=cpu()-c;
  if(cv::norm(result,functions[0](pool[(n-1)%count],320,237),cv::NORM_INF)!=0)throw std::runtime_error("timed mismatch");
  std::cout<<"pool="<<count<<" round="<<round<<" mode="<<names[k]<<" iterations="<<n<<" wall_us="<<elapsed/n<<" thread_cpu_us="<<used/n<<" equal=1\n";
 }
}catch(const std::exception&e){std::cerr<<e.what()<<'\n';return 1;}}
