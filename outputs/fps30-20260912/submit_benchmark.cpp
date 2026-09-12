#include "../../apps/face_recognition/pipeline.cpp"
#include <chrono>
#include <iostream>
namespace oldbench { using namespace rtctrl;
void require(bool b,const char*s){if(!b)throw std::runtime_error(s);}
#include "submit_old.inc"
}
class Fake final : public rtctrl::inference::Backend {
 public:
 rtctrl::inference::TensorSpec spec;
 std::vector<float> f;std::vector<unsigned char>b;bool ready=false;
 Fake(int side,bool u8,bool planar){spec.type=u8?rtctrl::inference::TensorType::UInt8:rtctrl::inference::TensorType::Float32;spec.layout=planar?rtctrl::inference::TensorLayout::NCHW:rtctrl::inference::TensorLayout::NHWC;spec.shape=planar?std::vector<uint32_t>{1,3,(unsigned)side,(unsigned)side}:std::vector<uint32_t>{1,(unsigned)side,(unsigned)side,3};f.resize(side*side*3);b.resize(side*side*3);}
 size_t input_count() const noexcept override{return 1;}
 const rtctrl::inference::TensorSpec& input_spec(size_t)const override{return spec;}
 rtctrl::inference::MutableTensorView get_input_buffer(size_t)override{ready=false;return{spec.type,spec.type==rtctrl::inference::TensorType::UInt8?static_cast<void*>(b.data()):static_cast<void*>(f.data()),spec.byte_size()};}
 bool commit_input(size_t)override{ready=true;return true;}
 bool prepare_input_data(const void*,size_t,size_t)override{return false;}
 bool run()override{return ready;}
};
int main(int argc,char**argv){try{
 int iterations=argc>1?std::stoi(argv[1]):500;if(iterations<1||iterations>100000)throw std::runtime_error("iterations");
 for(int side:{112,320})for(bool u8:{false,true})for(bool planar:{false,true})for(bool roi:{false,true}){
 cv::Mat backing(side,side+(roi?7:0),CV_8UC3);for(int y=0;y<backing.rows;y++)for(int x=0;x<backing.cols;x++)backing.at<cv::Vec3b>(y,x)=cv::Vec3b((x+y)%256,(2*x+y)%256,(x+3*y)%256);
 cv::Mat input=roi?backing(cv::Rect(3,0,side,side)):backing;
 Fake a(side,u8,planar),b(side,u8,planar);
 oldbench::submit(a,input,side);rtctrl::face::submit(b,input,side);
 if(u8?a.b!=b.b:a.f!=b.f)throw std::runtime_error("outputs differ");
 for(int round=0;round<4;round++)for(int slot=0;slot<2;slot++){
 bool fast=(round%2==0)?slot==1:slot==0;auto&dst=fast?b:a;
 auto begin=std::chrono::steady_clock::now();for(int i=0;i<iterations;i++){if(fast)rtctrl::face::submit(dst,input,side);else oldbench::submit(dst,input,side);}
 double us=std::chrono::duration<double,std::micro>(std::chrono::steady_clock::now()-begin).count()/iterations;
 if(u8?a.b!=b.b:a.f!=b.f)throw std::runtime_error("outputs differ after timed batch");
 std::cout<<"side="<<side<<" uint8="<<u8<<" planar="<<planar<<" roi="<<roi<<" round="<<round<<" fast="<<fast<<" us_per_submit="<<us<<" equal=1\n";
 }
 }
}catch(const std::exception&e){std::cerr<<e.what()<<'\n';return 1;}}
