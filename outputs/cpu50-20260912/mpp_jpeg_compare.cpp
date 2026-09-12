#include "jpeg_encoder.hpp"
#include <rk_mpi.h>
#include <mpp_buffer.h>
#include <mpp_frame.h>
#include <mpp_packet.h>
#include <mpp_meta.h>
#include <rk_venc_cfg.h>
#include <im2d.h>
#include <opencv2/imgcodecs.hpp>
#include <chrono>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <vector>
#include <ctime>
#include <cmath>
using Clock=std::chrono::steady_clock;
double ms(Clock::time_point t){return std::chrono::duration<double,std::milli>(Clock::now()-t).count();}
double cpu_ms(){timespec t{};clock_gettime(CLOCK_PROCESS_CPUTIME_ID,&t);return t.tv_sec*1000.0+t.tv_nsec/1000000.0;}
void ck(MPP_RET r,const char* op){if(r)throw std::runtime_error(std::string(op)+": "+std::to_string(r));}
struct Encoder {
 MppCtx ctx=nullptr;MppApi*api=nullptr;MppEncCfg cfg=nullptr;MppBufferGroup group=nullptr;MppBuffer input=nullptr,output=nullptr;
 rga_buffer_handle_t src_handle=0,dst_handle=0;cv::Mat image;std::vector<unsigned char> jpeg;
 const int width=960,height=712,stride=960,vstride=720;
 ~Encoder(){if(ctx)mpp_destroy(ctx);if(src_handle)releasebuffer_handle(src_handle);if(dst_handle)releasebuffer_handle(dst_handle);if(input)mpp_buffer_put(input);if(output)mpp_buffer_put(output);if(group)mpp_buffer_group_put(group);if(cfg)mpp_enc_cfg_deinit(cfg);}
 void init(const cv::Mat& bgr){
  image=bgr;ck(mpp_buffer_group_get_internal(&group,MPP_BUFFER_TYPE_DRM),"buffer group");
  ck(mpp_buffer_get(group,&input,stride*vstride*3/2),"input buffer");ck(mpp_buffer_get(group,&output,stride*vstride*3),"output buffer");
  jpeg.reserve(stride*vstride*3);
  src_handle=importbuffer_virtualaddr(image.data,static_cast<int>(image.step*image.rows));
  dst_handle=importbuffer_fd(mpp_buffer_get_fd(input),stride*vstride*3/2);
  if(!src_handle||!dst_handle)throw std::runtime_error("RGA import failed");
  ck(mpp_create(&ctx,&api),"mpp_create");RK_S64 timeout=1000;
  ck(api->control(ctx,MPP_SET_OUTPUT_TIMEOUT,&timeout),"output timeout");
  ck(api->control(ctx,MPP_SET_INPUT_TIMEOUT,&timeout),"input timeout");
  ck(mpp_init(ctx,MPP_CTX_ENC,MPP_VIDEO_CodingMJPEG),"mpp_init MJPEG");
  ck(mpp_enc_cfg_init(&cfg),"cfg init");ck(api->control(ctx,MPP_ENC_GET_CFG,cfg),"get cfg");
  auto set=[&](const char*k,int v){ck(mpp_enc_cfg_set_s32(cfg,k,v),k);};
  set("prep:width",width);set("prep:height",height);set("prep:hor_stride",stride);set("prep:ver_stride",vstride);
  set("prep:format",MPP_FMT_YUV420SP);set("prep:range",MPP_FRAME_RANGE_JPEG);set("codec:type",MPP_VIDEO_CodingMJPEG);
  set("rc:mode",MPP_ENC_RC_MODE_FIXQP);set("jpeg:q_factor",75);set("jpeg:qf_min",75);set("jpeg:qf_max",75);
  ck(api->control(ctx,MPP_ENC_SET_CFG,cfg),"set cfg");
 }
 void convert(){auto src=wrapbuffer_handle(src_handle,width,height,RK_FORMAT_BGR_888);auto dst=wrapbuffer_handle(dst_handle,width,height,RK_FORMAT_YCbCr_420_SP,stride,vstride);
  auto ret=imcvtcolor(src,dst,RK_FORMAT_BGR_888,RK_FORMAT_YCbCr_420_SP,IM_RGB_TO_YUV_BT601_FULL,1);
  if(ret!=IM_STATUS_SUCCESS&&ret!=IM_STATUS_NOERROR)throw std::runtime_error(imStrError(ret));
 }
 void encode(){MppFrame frame=nullptr;MppPacket packet=nullptr;
  // Follow SDK ownership: lightweight frame/packet descriptors per call;
  // all pixel/output DMA allocations and CPU output capacity are reused.
  try{
   ck(mpp_frame_init(&frame),"frame init");mpp_frame_set_width(frame,width);mpp_frame_set_height(frame,height);
   mpp_frame_set_hor_stride(frame,stride);mpp_frame_set_ver_stride(frame,vstride);mpp_frame_set_fmt(frame,MPP_FMT_YUV420SP);mpp_frame_set_buffer(frame,input);
   ck(mpp_packet_init_with_buffer(&packet,output),"packet init");mpp_packet_set_length(packet,0);
   ck(mpp_meta_set_packet(mpp_frame_get_meta(frame),KEY_OUTPUT_PACKET,packet),"set output packet");
   ck(api->encode_put_frame(ctx,frame),"put frame");mpp_frame_deinit(&frame);
   MppPacket result=nullptr;ck(api->encode_get_packet(ctx,&result),"get packet");
   if(!result)throw std::runtime_error("empty packet");
   if(result!=packet){mpp_packet_deinit(&packet);packet=result;}
   auto*data=static_cast<unsigned char*>(mpp_packet_get_pos(packet));auto size=mpp_packet_get_length(packet);
   if(!data||!size||size>static_cast<size_t>(stride*vstride*3)||mpp_packet_is_partition(packet))throw std::runtime_error("invalid/partitioned JPEG packet");
   jpeg.assign(data,data+size);mpp_packet_deinit(&packet);
  }catch(...){if(frame)mpp_frame_deinit(&frame);if(packet)mpp_packet_deinit(&packet);throw;}
 }
};
void save(const std::string&p,const std::vector<unsigned char>& data){std::ofstream f(p,std::ios::binary);f.write(reinterpret_cast<const char*>(data.data()),data.size());if(!f)throw std::runtime_error("save failed");}
int main(int argc,char**argv){try{
 int count=argc>1?std::stoi(argv[1]):50;std::string prefix=argc>2?argv[2]:"mpp-jpeg";if(count<1||count>1000)throw std::runtime_error("count 1..1000");
 cv::setNumThreads(1);cv::Mat image(712,960,CV_8UC3);unsigned seed=17;
 for(int y=0;y<712;++y)for(int x=0;x<960;++x){seed=seed*1664525u+1013904223u;image.at<cv::Vec3b>(y,x)={static_cast<unsigned char>((x/4+(seed>>28))&255),static_cast<unsigned char>((y/3+((x/80)&1)*60)&255),static_cast<unsigned char>((x+y)/6&255)};}
 if(argc>3){std::ifstream raw(argv[3],std::ios::binary);for(int row=0;row<image.rows;++row)raw.read(reinterpret_cast<char*>(image.ptr(row)),image.cols*3);if(!raw)throw std::runtime_error("raw BGR must contain 960x712x3 bytes");}
 auto t=Clock::now();Encoder mpp;mpp.init(image);double init=ms(t);rtctrl::face::JpegEncoder turbo("turbojpeg");std::vector<unsigned char> tj;
 double tm=0,rm=0,em=0,tc=0,hc=0;for(int i=0;i<count+5;++i){
  auto a=[&]{auto start=Clock::now();double cpu=cpu_ms();tj=turbo.encode(image,75);if(i>=5){tm+=ms(start);tc+=cpu_ms()-cpu;}};
  auto b=[&]{double cpu=cpu_ms();auto start=Clock::now();mpp.convert();double convert=ms(start);start=Clock::now();mpp.encode();if(i>=5){rm+=convert;em+=ms(start);hc+=cpu_ms()-cpu;}};
  if(i%2){a();b();}else{b();a();}
 }
 save(prefix+"-turbo.jpg",tj);save(prefix+"-mpp.jpg",mpp.jpeg);
 auto decoded=cv::imdecode(mpp.jpeg,cv::IMREAD_COLOR);auto reference=cv::imdecode(tj,cv::IMREAD_COLOR);
 if(decoded.size()!=image.size()||reference.size()!=image.size())throw std::runtime_error("decode dimensions wrong");
 std::cout<<"count="<<count<<" init_ms="<<init<<" turbo_ms="<<tm/count<<" rga_bgr_nv12_ms="<<rm/count<<" mpp_encode_copy_ms="<<em/count<<" hardware_total_ms="<<(rm+em)/count<<" turbo_cpu_ms="<<tc/count<<" hardware_process_cpu_ms="<<hc/count<<" turbo_bytes="<<tj.size()<<" mpp_bytes="<<mpp.jpeg.size()<<" decoded_width="<<decoded.cols<<" decoded_height="<<decoded.rows<<" decoded_max_delta="<<cv::norm(decoded,reference,cv::NORM_INF)<<" decoded_mean_delta="<<cv::norm(decoded,reference,cv::NORM_L1)/(960*712*3.0)<<"\n";
 auto metrics=[&](const char*name,const cv::Mat& decoded){double l2=cv::norm(decoded,image,cv::NORM_L2);double mse=l2*l2/(960*712*3.0);std::cout<<name<<" psnr_db="<<(mse?10*std::log10(255.0*255/mse):INFINITY)<<" mae="<<cv::norm(decoded,image,cv::NORM_L1)/(960*712*3.0)<<"\n";};metrics("turbo_source",reference);metrics("mpp_source",decoded);
 std::cout<<"NOTE: MPP q_factor=75 min=max75 is not guaranteed equivalent to libjpeg quality75; RGA BT601 full-range chroma conversion may differ. Validate output appearance and quality independently.\n";
 }catch(const std::exception&e){std::cerr<<e.what()<<"\n";return 1;}}
