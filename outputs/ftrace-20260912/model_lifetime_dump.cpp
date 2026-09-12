#include "rtctrl/adapters/rknn/backend.hpp"
#include <cmath>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <vector>
int main(int argc,char**argv){try{
 if(argc!=4)throw std::runtime_error("usage: model_lifetime_dump model detector|recognizer output.bin");
 bool det=std::string(argv[2])=="detector";if(!det&&std::string(argv[2])!="recognizer")throw std::runtime_error("role");
 rknn::NativeInputNormalization norm=det?rknn::NativeInputNormalization{{104,117,123},{1,1,1}}:rknn::NativeInputNormalization{{127.5,127.5,127.5},{127.5,127.5,127.5}};
 rknn::RknnBackend backend(argv[1],norm);
 // Keep touched allocations alive through inference. This encourages reuse of
 // freed regions; allocator placement is not guaranteed and is not a proof.
 std::vector<std::vector<unsigned char>> churn;
 for(unsigned i=0;i<32;i++)churn.emplace_back(1024*1024,static_cast<unsigned char>(0xa5^i));
 std::ifstream model(argv[1],std::ios::binary|std::ios::ate);
 if(!model||model.tellg()<=0)throw std::runtime_error("model length");
 churn.emplace_back(static_cast<size_t>(model.tellg()),0x5a);
 std::vector<unsigned char> input(backend.input_spec(0).byte_size());for(size_t j=0;j<input.size();j++)input[j]=(j*37)%256;
 std::ofstream out(argv[3],std::ios::binary|std::ios::trunc);if(!out)throw std::runtime_error("output open");
 size_t count=0;
 for(int run=0;run<20;run++){
  if(!backend.prepare_input_data(input.data(),input.size(),0)||!backend.run())throw std::runtime_error("inference");
  for(size_t tensor=0;tensor<backend.output_count();tensor++){
   const auto&v=backend.output_data(tensor);for(float f:v)if(!std::isfinite(f))throw std::runtime_error("nonfinite");
   out.write(reinterpret_cast<const char*>(v.data()),v.size()*sizeof(float));if(!out)throw std::runtime_error("output write");count+=v.size();
  }
 }
 out.close();if(!out)throw std::runtime_error("output close");
 size_t live=0;unsigned checksum=0;for(const auto&v:churn){live+=v.size();checksum+=v.front()+v.back();}
 std::cout<<"runs=20 finite=1 floats="<<count<<" live_churn_bytes="<<live<<" churn_checksum="<<checksum<<'\n';
}catch(const std::exception&e){std::cerr<<e.what()<<'\n';return 1;}}
