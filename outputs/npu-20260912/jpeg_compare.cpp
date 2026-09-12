#include "turbojpeg.h"
#include <opencv2/core.hpp>
#include <opencv2/imgcodecs.hpp>
#include <dlfcn.h>
#include <algorithm>
#include <chrono>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <vector>
using Clock = std::chrono::steady_clock;
double elapsed(Clock::time_point t) { return std::chrono::duration<double,std::milli>(Clock::now()-t).count(); }
template<class T> T symbol(void* lib, const char* name) {
    dlerror(); auto p = dlsym(lib,name); const char* e=dlerror();
    if(e || !p) throw std::runtime_error(e?e:name);
    return reinterpret_cast<T>(p);
}
struct Turbo {
    void* lib = nullptr;
    tjhandle compressor = nullptr, decoder = nullptr;
    decltype(&tjInitCompress) init;
    decltype(&tjInitDecompress) initdecode;
    decltype(&tjDestroy) destroy;
    decltype(&tjCompress2) compress;
    decltype(&tjBufSize) capacity;
    decltype(&tjGetErrorStr2) error;
    decltype(&tjDecompressHeader3) header;
    std::vector<unsigned char> output;
    unsigned long size = 0;
    Turbo(const char* path) {
        lib=dlopen(path,RTLD_NOW|RTLD_LOCAL);
        if(!lib) throw std::runtime_error(dlerror());
        init=symbol<decltype(init)>(lib,"tjInitCompress");
        initdecode=symbol<decltype(initdecode)>(lib,"tjInitDecompress");
        destroy=symbol<decltype(destroy)>(lib,"tjDestroy");
        compress=symbol<decltype(compress)>(lib,"tjCompress2");
        capacity=symbol<decltype(capacity)>(lib,"tjBufSize");
        error=symbol<decltype(error)>(lib,"tjGetErrorStr2");
        header=symbol<decltype(header)>(lib,"tjDecompressHeader3");
        compressor=init(); decoder=initdecode();
        if(!compressor || !decoder) throw std::runtime_error(error(nullptr));
        auto cap=capacity(960,712,TJSAMP_420);
        if(cap==static_cast<unsigned long>(-1)) throw std::runtime_error(error(compressor));
        output.resize(cap);
        Dl_info info{}; dladdr(reinterpret_cast<void*>(compress),&info);
        std::cout<<"loaded="<<(info.dli_fname?info.dli_fname:"unknown")<<" capacity="<<cap<<"\n";
    }
    ~Turbo() { if(compressor) destroy(compressor); if(decoder) destroy(decoder); if(lib) dlclose(lib); }
    void encode(const cv::Mat& bgr) {
        auto* ptr=output.data(); size=output.size();
        if(compress(compressor,bgr.data,bgr.cols,static_cast<int>(bgr.step),bgr.rows,TJPF_BGR,
                    &ptr,&size,TJSAMP_420,75,TJFLAG_NOREALLOC|TJFLAG_ACCURATEDCT)!=0)
            throw std::runtime_error(error(compressor));
        if(ptr!=output.data() || size>output.size()) throw std::runtime_error("output reallocated");
    }
    void inspect(const char* name,const unsigned char* data,unsigned long len) {
        int w=0,h=0,s=0,c=0;
        if(header(decoder,data,len,&w,&h,&s,&c)!=0) throw std::runtime_error(error(decoder));
        std::cout<<name<<" bytes="<<len<<" dimensions="<<w<<"x"<<h<<" subsampling="<<s<<" colorspace="<<c<<"\n";
        if(w!=960||h!=712||s!=TJSAMP_420) throw std::runtime_error("JPEG dimensions/subsampling mismatch");
    }
};
void save(const std::string& path,const unsigned char* data,size_t size) {
    std::ofstream out(path,std::ios::binary); out.write(reinterpret_cast<const char*>(data),size);
    if(!out)throw std::runtime_error("save failed: "+path);
}
int main(int argc,char** argv) {
    try {
        int count=argc>1?std::stoi(argv[1]):100;
        const char* library=argc>2?argv[2]:"/usr/lib/libturbojpeg.so.0";
        std::string prefix=argc>3?argv[3]:"jpeg-compare";
        if(count<1||count>10000)throw std::runtime_error("count must be 1..10000");
        auto t=Clock::now(); Turbo turbo(library); double initms=elapsed(t);
        t=Clock::now(); cv::Mat input(712,960,CV_8UC3);
        unsigned seed=17;
        for(int y=0;y<input.rows;++y) for(int x=0;x<input.cols;++x) {
            seed=seed*1664525u+1013904223u;
            // Gradients, edges and deterministic texture; identical every run.
            input.at<cv::Vec3b>(y,x)={static_cast<unsigned char>((x/4+(seed>>28))&255),
                static_cast<unsigned char>((y/3+((x/80)&1)*60)&255),static_cast<unsigned char>((x+y)/6&255)};
        }
        double inputms=elapsed(t);
        std::vector<unsigned char> encoded; encoded.reserve(turbo.output.size());
        const std::vector<int> params={cv::IMWRITE_JPEG_QUALITY,75};
        auto cvencode=[&]{if(!cv::imencode(".jpg",input,encoded,params))throw std::runtime_error("cv encode failed");};
        for(int i=0;i<5;++i){cvencode();turbo.encode(input);}
        double cvms=0,tjms=0; std::vector<double> cvs,tjs;
        cvs.reserve(count);tjs.reserve(count);
        for(int i=0;i<count;++i) {
            auto a=[&]{auto begin=Clock::now();cvencode();double ms=elapsed(begin);cvms+=ms;cvs.push_back(ms);};
            auto b=[&]{auto begin=Clock::now();turbo.encode(input);double ms=elapsed(begin);tjms+=ms;tjs.push_back(ms);};
            if(i%2){b();a();}else{a();b();}
        }
        turbo.inspect("opencv",encoded.data(),encoded.size());
        turbo.inspect("turbojpeg",turbo.output.data(),turbo.size);
        t=Clock::now();save(prefix+"-opencv.jpg",encoded.data(),encoded.size());
        save(prefix+"-turbojpeg.jpg",turbo.output.data(),turbo.size);double savems=elapsed(t);
        t=Clock::now(); auto cvdecoded=cv::imdecode(encoded,cv::IMREAD_COLOR);
        cv::Mat tjbytes(1,static_cast<int>(turbo.size),CV_8UC1,turbo.output.data());
        auto tjdecoded=cv::imdecode(tjbytes,cv::IMREAD_COLOR);double decodems=elapsed(t);
        if(cvdecoded.empty()||tjdecoded.empty())throw std::runtime_error("decode failed");
        auto report=[&](const char* n,double sum,std::vector<double>& v){std::sort(v.begin(),v.end());
            std::cout<<n<<" count="<<count<<" total_ms="<<sum<<" mean_ms="<<sum/count<<" median_ms="<<v[v.size()/2]<<" p95_ms="<<v[(v.size()-1)*95/100]<<"\n";};
        report("opencv",cvms,cvs);report("turbojpeg",tjms,tjs);
        std::cout<<"init_ms="<<initms<<" input_ms="<<inputms<<" save_ms="<<savems<<" decode_ms="<<decodems
                 <<" decoded_max_delta="<<cv::norm(cvdecoded,tjdecoded,cv::NORM_INF)
                 <<" decoded_mean_abs_delta="<<cv::norm(cvdecoded,tjdecoded,cv::NORM_L1)/(960.0*712*3)
                 <<" byte_equal="<<(encoded.size()==turbo.size && std::equal(encoded.begin(),encoded.end(),turbo.output.begin()))<<"\n";
    }catch(const std::exception& e){std::cerr<<e.what()<<"\n";return 1;}
}
