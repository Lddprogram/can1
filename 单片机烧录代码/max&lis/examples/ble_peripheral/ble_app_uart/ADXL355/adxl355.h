#ifndef AT24C02_H__
#define AT24C02_H__
#include "nrf_delay.h"
#include "MyLog.h"

//I2C引脚定义
#define ADXL355_CTRL_IO     17        //adxl355控制引脚      
#define TWI_SCL_M           6         //I2C SCL引脚
#define TWI_SDA_M           7         //I2C SDA引脚

//参数定义
#define ODR_500_HZ 0x00    // 500 Hz 的配置值
#define ADXL355_RESET_VALUE 0x52
#define ADXL355_ADDRESS_LEN  1         //adxl355地址长度
#define ADXL355_ADDRESS     0x1D  //adxl355地址
#define ADXL355_WHO_AM_I 0xAD	//这个是DEVID_AD寄存器的地址下的值


//寄存器定义
#define XL355_DEVID_AD			    0x00	//模拟ID   值为0xAD 
#define XL355_DEVID_MST			    0x01    //模拟集成ID    前两个ID应该是354，跟模拟器件相关的地址
#define XL355_PARTID				0x02	//器件ID   这个应该是355的，储存0xED的地址
#define XL355_REVID					0x03	//产品修订ID
#define XL355_STATUS				0x04	//状态寄存器 
#define XL355_FIFO_ENTRIES	        0x05	//FIFO使能寄存器  

#define XL355_TEMP2					0x06	//温度寄存器（高4位）
#define XL355_TEMP1					0x07	//温度寄存器（低12位）

#define XL355_XDATA3				0x08	
#define XL355_XDATA2				0x09
#define XL355_XDATA1				0x0A	//X轴加速度数据，共20位，左对齐，以DATA3+DATA2+DATA1的形式连起来，然后末尾的4位无效

#define XL355_YDATA3				0x0B
#define XL355_YDATA2				0x0C
#define XL355_YDATA1				0x0D	//Y轴加速度数据
	
#define XL355_ZDATA3				0x0E
#define XL355_ZDATA2				0x0F
#define XL355_ZDATA1				0x10	//Z轴加速度数据

#define XL355_FIFO_DATA			    0x11	//FIFO的位置指针

#define XL355_OFFSET_X_H		    0x1E
#define XL355_OFFSET_X_L		    0x1F	//X轴偏置16位[15:0]，对应XDATA中的[19:4]

#define XL355_OFFSET_Y_H		    0x20
#define XL355_OFFSET_Y_L		    0x21	//Y轴偏置16位[15:0]，对应YDATA中的[19:4]

#define XL355_OFFSET_Z_H		    0x22
#define XL355_OFFSET_Z_L		    0x23	//Z轴偏置16位[15:0]，对应ZDATA中的[19:4]

#define XL355_ACT_EN				0x24	//活动使能寄存器   活动检测  判断振动传感器是否是根据实际的振动产生数值？
#define XL355_ACT_THRESH_H	        0x25
#define XL355_ACT_THRESH_L	        0x26	//活动阈值配置  当加速度超过该阈值才发生计数  其中该阈值的[15:0]，对应3轴的[18:3]
#define XL355_ACT_COUNT			    0x27	//活动阈值事件计数

#define XL355_FILTER				0x28	//滤波配置: 内部有高通滤波为[7:4]和低通滤波为[3:0] 
#define XL355_FIFO_SAMPLES	        0x29	//FIFO数量寄存器 默认0x60 即96个全用 配置位为[6:0]
#define XL355_INT_MAP				0x2A	//中断配置寄存器，包括两个INT的引脚  两个INT功能一样
#define XL355_SYNC					0x2B	//外部时钟触发控制
#define XL355_RANGE					0x2C	//I2c速度，中断极性，量程测量范围配置
#define XL355_POWER_CTL			    0x2D	//电源控制
#define XL355_SELF_TEST			    0x2E	//自测功能
#define XL355_RESET					0x2F	//复位值为0x52，类似于上电复位

//原始加速度数据结构体
typedef struct {
    uint32_t AccX;
    uint32_t AccY;
    uint32_t AccZ;
} Pure_Acc;



void twi_master_init(void);

/**
  @brief Function for writing a adxl355 register contents over TWI.
  @param[in]  register_address Register address to start writing to
  @param[in] value Value to write to register
  @retval true Register write succeeded
  @retval false Register write failed
*/
bool adxl355_register_write(uint8_t register_address, const uint8_t value);

/**
  @brief Function for reading adxl355 register contents over TWI.
  Reads one or more consecutive registers.
  @param[in]  register_address Register address to start reading from
  @param[in]  number_of_bytes Number of bytes to read
  @param[out] destination Pointer to a data buffer where read data will be stored
  @retval true Register read succeeded
  @retval false Register read failed
*/
bool adxl355_register_read(uint8_t register_address, uint8_t *destination, uint8_t number_of_bytes);

/**
  @brief Function for reading and verifying adxl355 product ID.
  @retval true Product ID is what was expected
  @retval false Product ID was not what was expected
*/
bool adxl355_verify_product_id(void);

bool adxl355_Start_Sensor(void);

bool adxl355_init(void);

int32_t ADXL355_Acceleration_Data_Conversion (uint32_t ui32SensorData);

bool adxl355_ReadAcc( int32_t *pACC_X , int32_t *pACC_Y , int32_t *pACC_Z );

void Power_SW_nrf_On(uint32_t Pin_Number);
void Power_SW_nrf_Off(uint32_t Pin_Number);

void Adxl355_data_send(void);

#endif


