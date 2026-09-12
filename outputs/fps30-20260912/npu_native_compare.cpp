#include <rknn_api.h>
#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstring>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <vector>
#include <time.h>
using Clock=std::chrono::steady_clock;
static double wall() { return std::chrono::duration<double,std::micro>(Clock::now().time_since_epoch()).count(); }
static double cpu() { timespec t{}; if(clock_gettime(CLOCK_THREAD_CPUTIME_ID,&t)) throw std::runtime_error("clock"); return t.tv_sec*1e6+t.tv_nsec/1e3; }
static void ck(int r,const char* s){if(r<0)throw std::runtime_error(std::string(s)+":"+std::to_string(r));}
struct Model {
    rknn_context c=0; rknn_tensor_mem* mem=nullptr;
    rknn_tensor_attr native{};
    std::vector<std::vector<float>> values;
    std::vector<rknn_output> outs;
    ~Model(){if(mem)rknn_destroy_mem(c,mem); if(c)rknn_destroy(c);}
    void init(std::vector<char>& model){
        ck(rknn_init(&c,model.data(),model.size(),0,nullptr),"init");
        rknn_input_output_num n{}; ck(rknn_query(c,RKNN_QUERY_IN_OUT_NUM,&n,sizeof(n)),"counts");
        if(n.n_input!=1||!n.n_output)throw std::runtime_error("single input required");
        ck(rknn_query(c,RKNN_QUERY_NATIVE_INPUT_ATTR,&native,sizeof(native)),"native");
        std::cout << "native_attr type=" << native.type << " fmt=" << native.fmt << " qnt=" << native.qnt_type << " zp=" << native.zp << " scale=" << native.scale << " dims=";
        for(uint32_t d=0;d<native.n_dims && d<RKNN_MAX_DIMS;d++)std::cout<<native.dims[d]<<',';
        std::cout << " size=" << native.size << " size_with_stride=" << native.size_with_stride << " elems=" << native.n_elems << " w_stride=" << native.w_stride << " h_stride=" << native.h_stride << std::endl;
        if(native.type!=RKNN_TENSOR_FLOAT16||native.fmt!=RKNN_TENSOR_NHWC||native.n_dims!=4||native.dims[0]!=1||native.dims[3]!=3||!(native.qnt_type==RKNN_TENSOR_QNT_NONE||(native.qnt_type==RKNN_TENSOR_QNT_AFFINE_ASYMMETRIC&&native.zp==0&&native.scale==1.0f))||native.size_with_stride!=native.n_elems*2||(native.w_stride&&native.w_stride!=native.dims[2]))throw std::runtime_error("unsupported native layout; refuse guess");
        values.resize(n.n_output); outs.resize(n.n_output);
        for(uint32_t i=0;i<n.n_output;i++){
            rknn_tensor_attr a{};a.index=i;ck(rknn_query(c,RKNN_QUERY_OUTPUT_ATTR,&a,sizeof(a)),"outputattr");
            values[i].resize(a.n_elems);
        }
    }
    void allocate(){
        mem=rknn_create_mem2(c,native.size_with_stride,RKNN_FLAG_MEMORY_CACHEABLE);
        if(!mem||!mem->virt_addr)throw std::runtime_error("cacheable create_mem2 failed");
        native.pass_through=1;
        ck(rknn_set_io_mem(c,mem,&native),"bind native input");
        std::cout<<"native_mem flags="<<mem->flags<<" size="<<mem->size<<" requested_cacheable=1 pass_through=1\n";
    }
    void get(){
        for(size_t i=0;i<outs.size();i++){outs[i]={};outs[i].index=i;outs[i].want_float=1;outs[i].is_prealloc=1;outs[i].buf=values[i].data();outs[i].size=values[i].size()*4;}
        ck(rknn_outputs_get(c,outs.size(),outs.data(),nullptr),"get");
        bool good=true;for(size_t i=0;i<outs.size();i++)good &= outs[i].buf==values[i].data()&&outs[i].size==values[i].size()*4;
        int released=rknn_outputs_release(c,outs.size(),outs.data());ck(released,"release");
        if(!good)throw std::runtime_error("output buffer mismatch");
        for(const auto& v:values)for(float x:v)if(!std::isfinite(x))throw std::runtime_error("nonfinite output");
    }
};
static double error(const Model&a,const Model&b){
    if(a.values.size()!=b.values.size())throw std::runtime_error("count mismatch");
    double e=0;for(size_t i=0;i<a.values.size();i++){if(a.values[i].size()!=b.values[i].size())throw std::runtime_error("shape mismatch");for(size_t j=0;j<a.values[i].size();j++)e=std::max(e,std::abs(double(a.values[i][j])-b.values[i][j]));}return e;
}
int main(int argc,char**argv){try{
    if(argc!=4)throw std::runtime_error("usage: npu_native_compare model.rknn detector|recognizer repeats");
    bool detector=std::string(argv[2])=="detector";
    if(!detector&&std::string(argv[2])!="recognizer")throw std::runtime_error("role");
    int rounds=std::stoi(argv[3]);if(rounds<1||rounds>10000)throw std::runtime_error("rounds");
    std::ifstream f(argv[1],std::ios::binary|std::ios::ate);if(!f)throw std::runtime_error("file");auto len=f.tellg();if(len<=0||uint64_t(len)>UINT32_MAX)throw std::runtime_error("size");std::vector<char> bytes(static_cast<size_t>(len));f.seekg(0);f.read(bytes.data(),len);if(!f)throw std::runtime_error("read");
    Model ref,native;ref.init(bytes);native.init(bytes);native.allocate();
    if(ref.native.n_elems!=native.native.n_elems)throw std::runtime_error("input mismatch");
    std::vector<uint8_t> pixels(ref.native.n_elems);for(size_t j=0;j<pixels.size();j++)pixels[j]=(j*37)%256;
    float mean[3]={detector?104.f:127.5f,detector?117.f:127.5f,detector?123.f:127.5f};float stddev=detector?1.f:127.5f;
    auto execute=[&](bool direct,bool normalized,int pair,bool print){
        Model&m=direct?native:ref;
        double w[5],c[5];w[0]=wall();c[0]=cpu();
        if(direct){auto* dst=static_cast<__fp16*>(m.mem->virt_addr);for(size_t j=0;j<pixels.size();j++){float x=pixels[j];if(normalized)x=(x-mean[j%3])/stddev;dst[j]=static_cast<__fp16>(x);}}
        else{rknn_input in{};in.index=0;in.type=RKNN_TENSOR_UINT8;in.fmt=RKNN_TENSOR_NHWC;in.pass_through=0;in.buf=pixels.data();in.size=pixels.size();ck(rknn_inputs_set(m.c,1,&in),"inputs_set");}
        w[1]=wall();c[1]=cpu();
        if(direct)ck(rknn_mem_sync(m.c,m.mem,RKNN_MEMORY_SYNC_TO_DEVICE),"sync_to_device");
        w[2]=wall();c[2]=cpu();ck(rknn_run(m.c,nullptr),"run");w[3]=wall();c[3]=cpu();m.get();w[4]=wall();c[4]=cpu();
        if(print){std::cout<<"sample pair="<<pair<<" native="<<direct<<" normalized="<<normalized;const char* names[]={"fill_or_set","sync","run","get_release"};for(int i=0;i<4;i++)std::cout<<' '<<names[i]<<"_wall_us="<<w[i+1]-w[i]<<' '<<names[i]<<"_cpu_us="<<c[i+1]-c[i];std::cout<<" total_wall_us="<<w[4]-w[0]<<" total_cpu_us="<<c[4]-c[0]<<'\n';}
    };
    for(int i=0;i<3;i++)execute(false,false,-1,false);
    bool accepted[2]={false,false};
    for(int mode=0;mode<2;mode++){
        execute(true,mode,-1,false);double e=error(ref,native);accepted[mode]=e<=1e-5;
        std::cout<<"candidate normalized="<<mode<<" finite=1 max_abs_error="<<e<<" accepted="<<accepted[mode]<<'\n';
    }
    for(int mode=0;mode<2;mode++)if(accepted[mode]){
        for(int pair=-3;pair<rounds;pair++){
            for(int slot=0;slot<2;slot++)execute(((pair+4)%2==0)?slot==1:slot==0,mode,pair,pair>=0);
            double e=error(ref,native);if(pair>=0)std::cout<<"comparison pair="<<pair<<" normalized="<<mode<<" max_abs_error="<<e<<'\n';if(e>1e-5)throw std::runtime_error("equivalence lost");
        }
    }
    std::cout<<"completed candidates_accepted="<<(accepted[0]+accepted[1])<<" flags_disable_flush=0 explicit_sync=1\n";
    return (accepted[0]||accepted[1])?0:3;
}catch(const std::exception&e){std::cerr<<"ERROR "<<e.what()<<'\n';return 1;}}
