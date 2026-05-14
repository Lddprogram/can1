/****************************************Copyright (c)************************************************

** Descriptions:		ADXL355驱动程序
**---------------------------------------------------------------------------------------------------*/
#include <stdbool.h>
#include <stdint.h>
#include <string.h>
#include "boards.h"
#include "nrf_drv_twi.h"
#include "adxl355.h"


//TWI驱动程序实例ID,ID和外设编号对应，0:TWI0  1:TWI1
#define TWI_INSTANCE_ID     0

//TWI传输完成标志
static volatile bool m_xfer_done = false;
//定义TWI驱动程序实例，名称为m_twi
static const nrf_drv_twi_t m_twi = NRF_DRV_TWI_INSTANCE(TWI_INSTANCE_ID);

//TWI事件处理函数
void twi_handler(nrf_drv_twi_evt_t const * p_event, void * p_context)
{
    //判断TWI事件类型
	  switch (p_event->type)
    {
        //传输完成事件
			  case NRF_DRV_TWI_EVT_DONE:
            m_xfer_done = true;//置位传输完成标志
            break;
        default:
            break;
    }
}
//TWI初始化
void twi_master_init(void)
{
    ret_code_t err_code;
    //定义并初始化TWI配置结构体
    const nrf_drv_twi_config_t twi_config = {
       .scl                = TWI_SCL_M,  //定义TWI SCL引脚
       .sda                = TWI_SDA_M,  //定义TWI SDA引脚
       .frequency          = NRF_DRV_TWI_FREQ_100K, //TWI速率
       .interrupt_priority = APP_IRQ_PRIORITY_HIGH, //TWI优先级
       .clear_bus_init     = false//初始化期间不发送9个SCL时钟
    };
    //初始化TWI
    err_code = nrf_drv_twi_init(&m_twi, &twi_config, twi_handler, NULL);
	//检查返回的错误代码
    APP_ERROR_CHECK(err_code);
    //使能TWI
    nrf_drv_twi_enable(&m_twi);
}
/*************************************************************************
 * 功  能 : 主控供电开关
 * 参  数 : SW对应引脚   SW：17
 * 返回值 : 无
 *************************************************************************/ 
void Power_SW_nrf_On(uint32_t Pin_Number)
{
	nrf_gpio_cfg_output(Pin_Number);
	nrf_gpio_pin_set(Pin_Number);
}

void Power_SW_nrf_Off(uint32_t Pin_Number)
{
	nrf_gpio_cfg_output(Pin_Number);
	nrf_gpio_pin_write(Pin_Number, 0);
}
/*************************************************************************
 * 功  能 : 写ADXL355寄存器
 * 参  数 : register_address[in]：寄存器地址
 *        : value[in]：写入的数据
 * 返回值 : true:写数据成功,false：写入失败
 *************************************************************************/ 
bool adxl355_register_write(uint8_t register_address, uint8_t value)
{
	  ret_code_t err_code;
	  uint8_t tx_buf[ADXL355_ADDRESS_LEN+1];
	
	  //准备写入的数据
		tx_buf[0] = register_address;
    tx_buf[1] = value;
	  //TWI传输完成标志设置为false
		m_xfer_done = false;
		//写入数据
    err_code = nrf_drv_twi_tx(&m_twi, ADXL355_ADDRESS, tx_buf, ADXL355_ADDRESS_LEN+1, false);
	  //等待TWI总线传输完成
		while (m_xfer_done == false){}
	  if (NRF_SUCCESS != err_code)
    {
        return false;
    }
		return true;	
}
/*************************************************************************
 * 功  能 : 读ADXL355寄存器
 * 参  数 : register_address[in]：寄存器地址
 *        : * destination[out]  ：指向保存读取数据的缓存
 *        : number_of_bytes[in] ：读取的数据长度
 * 返回值 : true:操作成功,false：操作失败
 *************************************************************************/ 
bool adxl355_register_read(uint8_t register_address, uint8_t * destination, uint8_t number_of_bytes)
{
	  ret_code_t err_code;
	  //TWI传输完成标志设置为false
		m_xfer_done = false;
	  err_code = nrf_drv_twi_tx(&m_twi, ADXL355_ADDRESS, &register_address, 1, true);
	  //等待TWI总线传输完成
		while (m_xfer_done == false){}
    if (NRF_SUCCESS != err_code)
    {
        return false;
    }
		//TWI传输完成标志设置为false
		m_xfer_done = false;
	  err_code = nrf_drv_twi_rx(&m_twi, ADXL355_ADDRESS, destination, number_of_bytes);
		//等待TWI总线传输完成
		while (m_xfer_done == false){}
		if (NRF_SUCCESS != err_code)
    {
        return false;
    }
		return true;
}
/*************************************************************************
 * 功  能 : 验证adxl355是否连接成功，通过比对XL355_DEVID_AD实际的值与识别的值（储存到了who_am_i里）确定
 * 参  数 : 无
 * 返回值 : true:验证成功，false：验证失败 
 *************************************************************************/ 
bool adxl355_verify_product_id(void)
{
    uint8_t who_am_i;

    if (adxl355_register_read(XL355_DEVID_AD, &who_am_i, 1))
    {
        if (who_am_i != ADXL355_WHO_AM_I)
        {
            return false;
        }
        else
        {
            return true;
        }
    }
    else
    {
        return false;
    }
}
/*************************************************************************
 * 功  能 : ADXL355供电开启
 * 参  数 : 无
 * 返回值 : true:初始化成功，false：初始化失败
 *************************************************************************/ 
bool adxl355_Start_Sensor(void)
{
	uint8_t ui8temp;
	bool Start_check = true;
	Start_check &= adxl355_register_read(XL355_POWER_CTL, &ui8temp, 1);      /* Read POWER_CTL register, before modifying it */
	ui8temp = ui8temp & 0xFE;                                        /* Set measurement bit in POWER_CTL register */
	Start_check &= adxl355_register_write(XL355_POWER_CTL, ui8temp);       /* Write the new value to POWER_CTL register */
	
	return Start_check;
}

/*************************************************************************
 * 功  能 : 初始化ADXL355
 * 参  数 : 无
 * 返回值 : true:初始化成功，false：初始化失败
 *************************************************************************/ 
bool adxl355_init(void)
{   
	bool transfer_succeeded = true;
	
  //验证adxl355是否连接成功
	transfer_succeeded &= adxl355_verify_product_id();
		if(adxl355_verify_product_id() == false)
		{
			return false;
		}

  //唤醒adxl355
	transfer_succeeded &= adxl355_Start_Sensor(); 
  
	//设置传感器参数
	(void)adxl355_register_write(XL355_RANGE , 0x81); //设置为 1000 0001 高速模式  ±2g          
	(void)adxl355_register_write(XL355_SYNC , 0x03); 	//关闭外部时钟控制						
	(void)adxl355_register_write(XL355_FILTER, ODR_500_HZ); // 设置FILTER寄存器,配置输出数据率500 Hz  


  return transfer_succeeded;
}
/*************************************************************************
 * 功  能 : ADXL355加速度数据转换
 * 参  数 : uint32_t ui32SensorData 加速度原始值，可以是Pure_Acc结构体中的AccX，AccY，AccZ
 * 返回值 : 处理后的加速度值 int32_t
 *************************************************************************/ 
int32_t ADXL355_Acceleration_Data_Conversion (uint32_t ui32SensorData)
{
   int32_t volatile i32Conversion = 0;

	//加速度数据为20位 读取的3个字节（24位）加速度数据其中最低4位无效[3:0]     00000000 xxxxxxxx xxxxxxxx xxxxxxxx
   ui32SensorData = (ui32SensorData  >> 4);                  //右移4位
   ui32SensorData = (ui32SensorData & 0x000FFFFF);           //得到32位真实的数据 00000000 0000xxxx xxxxxxxx xxxxxxxx
   if((ui32SensorData & 0x00080000)  == 0x00080000)          //如果数据是  00000000 00001xxx xxxxxxxx xxxxxxxx
	 {
         i32Conversion = (ui32SensorData | 0xFFF00000);      //则数据转换成 11111111 11111xxx xxxxxxxx xxxxxxxx
   }
   else
	 {
         i32Conversion = ui32SensorData;                     //否则数据转换成  00000000 0000xxxx xxxxxxxx xxxxxxxx
   }
   return i32Conversion;
}

/*************************************************************************
 * 功  能 : 读加速度原始值,并进行有符号化转换
 * 参  数 : pACC_X[in]：加速度x轴的数据（带符号）
 *        : pACC_Y[in]：加速度y轴的数据（带符号）
 *        : pACC_Z[in]：加速度z轴的数据（带符号）
 * 返回值 : true:读取成功，false：读取失败
 *************************************************************************/ 
bool adxl355_ReadAcc( int32_t *pACC_X , int32_t *pACC_Y , int32_t *pACC_Z )
{
	uint32_t Ax, Ay, Az;
	uint8_t buf[9];
  bool ret = false;		
  if(adxl355_register_read(XL355_XDATA3, buf, 9) == true)
	{
		adxl355_register_read(XL355_XDATA3, buf, 9);
		Ax = 0x00FFFFFF & ((buf[0] << 16) | (buf[1] << 8) | buf[2]);
		Ay = 0x00FFFFFF & ((buf[3] << 16) | (buf[4] << 8) | buf[5]);
		Az = 0x00FFFFFF & ((buf[6] << 16) | (buf[7] << 8) | buf[8]);
		*pACC_X = ADXL355_Acceleration_Data_Conversion(Ax);
		*pACC_Y = ADXL355_Acceleration_Data_Conversion(Ay);
		*pACC_Z = ADXL355_Acceleration_Data_Conversion(Az);
		
		ret = true;
		
	}
	return ret;
}

/*************************************************************************
 * 功  能 : 加速度数据字符串蓝牙发送
 * 参  数 : 无
 * 返回值 : 无
 *************************************************************************/ 
void Adxl355_data_send(void)
{
	static int32_t AccValue[3];
	char accel_output[110]; 
	if(adxl355_ReadAcc( &AccValue[0], &AccValue[1] , &AccValue[2]) == true)
		 {
			//数据整合成字符串
			 snprintf(accel_output, sizeof(accel_output),
                "n");
//                AccValue[0],
//                AccValue[1],
//                AccValue[2]);
			 
		 }
		 else
		 {
			 snprintf(accel_output, sizeof(accel_output),"Read ACC failed");

		 }
	MY_LOG_DEBUG("%s", accel_output);
	ble_send(accel_output,sizeof(accel_output));	
}




