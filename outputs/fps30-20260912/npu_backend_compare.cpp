#include "rtctrl/adapters/rknn/backend.hpp"
#include <algorithm>
#include <chrono>
#include <cmath>
#include <iostream>
#include <stdexcept>
#include <vector>
#include <time.h>
using Clock=std::chrono::steady_clock;
static double wall(){return std::chrono::duration<double,std::micro>(Clock::now().time_since_epoch()).count();}
static double cpu(){timespec t{};if(clock_gettime(CLOCK_THREAD_CPUTIME_ID,&t))throw std::runtime_error("clock");return t.tv_sec*1e6+t.tv_nsec/1e3;}
int main(int argc,char**argv){try{
 if(argc!=4)throw std::runtime_error("usage: npu_backend_compare model detector|recognizer pairs");
 bool det=std::string(argv[2])=="detector"; if(!det&&std::string(argv[2])!="recognizer")throw std::runtime_error("role");
 int count=std::stoi(argv[3]);if(count<1||count>10000)throw std::runtime_error("count");
 rknn::NativeInputNormalization norm=det?rknn::NativeInputNormalization{{104,117,123},{1,1,1}}:rknn::NativeInputNormalization{{127.5,127.5,127.5},{127.5,127.5,127.5}};
 rknn::RknnBackend baseline(argv[1],rknn::RknnBackend::TensorType::UInt8),native(argv[1],norm);
 if(baseline.input_spec(0).byte_size()!=native.input_spec(0).byte_size())throw std::runtime_error("shape");
 std::vector<unsigned char> pixels(baseline.input_spec(0).byte_size());for(size_t i=0;i<pixels.size();i++)pixels[i]=(i*37)%256;
 double max_error=0;
 for(int pair=-3;pair<count;pair++){
  for(int slot=0;slot<2;slot++){
   bool direct=((pair+4)%2==0)?slot==1:slot==0;auto& b=direct?native:baseline;
   double w=wall(),c=cpu();if(!b.prepare_input_data(pixels.data(),pixels.size(),0)||!b.run())throw std::runtime_error("backend run");
   double elapsed=wall()-w,used=cpu()-c;
   if(pair>=0)std::cout<<"sample pair="<<pair<<" native="<<direct<<" wall_us="<<elapsed<<" thread_cpu_us="<<used<<'\n';
  }
  if(baseline.output_count()!=native.output_count())throw std::runtime_error("output count");
  double e=0;
  for(size_t i=0;i<baseline.output_count();i++){const auto&a=baseline.output_data(i);const auto&b=native.output_data(i);if(a.size()!=b.size())throw std::runtime_error("output size");for(size_t j=0;j<a.size();j++){if(!std::isfinite(a[j])||!std::isfinite(b[j]))throw std::runtime_error("nonfinite");e=std::max(e,std::abs(double(a[j])-b[j]));}}
  max_error=std::max(max_error,e);if(pair>=0)std::cout<<"comparison pair="<<pair<<" finite=1 max_abs_error="<<e<<'\n';if(e>1e-5)throw std::runtime_error("not equivalent");
 }
 std::cout<<"result max_abs_error="<<max_error<<'\n';return 0;
}catch(const std::exception&e){std::cerr<<"ERROR "<<e.what()<<'\n';return 1;}}
