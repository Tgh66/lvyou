import streamlit as st
import datetime
import requests
import folium
import math
import random
from streamlit_folium import st_folium

# ====================
# 0. 页面配置与样式
# ====================
st.set_page_config(page_title="百度全能旅游助手", layout="wide", page_icon="🐼")

st.markdown("""
<style>
    .weather-card {
        background: linear-gradient(120deg, #a1c4fd 0%, #c2e9fb 100%);
        padding: 12px;
        border-radius: 12px;
        text-align: center;
        color: #2c3e50;
        box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        margin-bottom: 10px;
        border: 1px solid #fff;
    }
    .weather-date { font-size: 14px; color: #555; }
    .weather-icon { font-size: 32px; margin: 5px 0; }
    .weather-temp { font-size: 20px; font-weight: bold; color: #e65100; }
    .weather-desc { font-size: 15px; font-weight: 500; }
    .stButton>button { border-radius: 20px; width: 100%; }
</style>
""", unsafe_allow_html=True)

# ====================
# 1. 坐标转换工具 (百度 BD09 <-> 国际 WGS84)
# ====================
x_pi = 3.14159265358979324 * 3000.0 / 180.0

def bd09_to_wgs84(bd_lon, bd_lat):
    """
    百度坐标系(BD09) 转 WGS84
    用于将百度搜到的点，准确画在 Folium 地图上
    """
    x = bd_lon - 0.0065
    y = bd_lat - 0.006
    z = math.sqrt(x * x + y * y) - 0.00002 * math.sin(y * x_pi)
    theta = math.atan2(y, x) - 0.000003 * math.cos(x * x_pi)
    gg_lon = z * math.cos(theta)
    gg_lat = z * math.sin(theta)
    # 简单近似转 WGS84
    return gg_lat, gg_lon

# ====================
# 2. 百度天气模块 (核心重写)
# ====================
def get_baidu_weather(city_name, ak):
    """
    三步走策略获取百度天气：
    1. 搜索城市 -> 拿到坐标
    2. 逆地理编码 -> 拿到 adcode (行政区划ID)
    3. 天气API -> 使用 adcode 查天气
    """
    session = requests.Session()
    session.trust_env = False # ⛔ 禁用代理，防止学校网络 404
    
    forecasts = []
    
    try:
        # --- 步骤 1: 获取城市坐标 ---
        # 使用 Place API 获取城市中心点
        geo_url = "https://api.map.baidu.com/place/v2/search"
        geo_params = {"query": city_name, "region": city_name, "output": "json", "ak": ak, "page_size": 1}
        
        geo_res = session.get(geo_url, params=geo_params).json()
        if geo_res['status'] != 0 or not geo_res['results']:
            print("步骤1失败: 找不到城市")
            return get_mock_weather(), "MOCK_CITY"
            
        location = geo_res['results'][0]['location'] # {lat: ..., lng: ...}
        
        # --- 步骤 2: 获取行政代码 (adcode) ---
        # 必须用 Reverse Geocoding API
        reg_url = "https://api.map.baidu.com/reverse_geocoding/v3/"
        reg_params = {
            "ak": ak,
            "output": "json",
            "coordtype": "bd09ll",
            "location": f"{location['lat']},{location['lng']}"
        }
        
        reg_res = session.get(reg_url, params=reg_params).json()
        if reg_res['status'] != 0:
            print("步骤2失败: 无法获取行政区号")
            return get_mock_weather(), "MOCK_ADCODE"
            
        district_id = reg_res['result']['addressComponent']['adcode']
        
        # --- 步骤 3: 查天气 (Weather v1) ---
        weather_url = "https://api.map.baidu.com/weather/v1/"
        weather_params = {
            "district_id": district_id,
            "data_type": "all", # all = 实况 + 预报
            "ak": ak
        }
        
        w_res = session.get(weather_url, params=weather_params).json()
        
        if w_res['status'] == 0:
            # 解析百度返回的天气数据
            # 百度返回的是 forecast: list
            for day in w_res['result']['forecasts']:
                # 简单映射图标
                text = day['text_day']
                icon = "🌥️"
                if "晴" in text: icon = "🌞"
                elif "云" in text or "阴" in text: icon = "⛅"
                elif "雨" in text: icon = "🌧"
                elif "雪" in text: icon = "❄️"
                elif "风" in text: icon = "🌪"
                
                forecasts.append({
                    "date": f"{day['date']} {day['week']}",
                    "icon": icon,
                    "text": f"{day['text_day']} | {day['wind_dir_day']}",
                    "temp": f"{day['low']}° ~ {day['high']}°C"
                })
            return forecasts, "BAIDU"
        else:
            print(f"步骤3失败: 百度天气API报错 {w_res['status']} - {w_res['message']}")
            # 如果AK没开通天气权限，会进这里
            return get_mock_weather(), "MOCK_API_FAIL"
            
    except Exception as e:
        print(f"网络或其他错误: {e}")
        return get_mock_weather(), "MOCK_NET_ERR"

def get_mock_weather():
    """兜底模拟数据：保证 AK 权限不够时界面依然能看"""
    mock = []
    base = datetime.date.today()
    for i in range(4):
        d = base + datetime.timedelta(days=i)
        t = random.randint(18, 28)
        mock.append({
            "date": d.strftime("%Y-%m-%d"),
            "icon": random.choice(["🌞", "⛅", "🌧"]),
            "text": random.choice(["晴朗", "多云", "小雨"]),
            "temp": f"{t-5}° ~ {t}°C"
        })
    return mock

# ====================
# 3. 百度地图搜索模块
# ====================
def search_spots_baidu(keyword, city, ak):
    session = requests.Session()
    session.trust_env = False
    
    url = "https://api.map.baidu.com/place/v2/search"
    params = {"query": keyword, "region": city, "output": "json", "ak": ak, "scope": 2, "page_size": 6}
    
    spots = []
    try:
        res = session.get(url, params=params).json()
        if res['status'] == 0:
            for item in res['results']:
                loc = item['location']
                # 转换坐标用于 Folium 地图显示
                w_lat, w_lon = bd09_to_wgs84(loc['lng'], loc['lat'])
                
                spots.append({
                    "name": item['name'],
                    "addr": item.get('address', '地址未收录'),
                    "score": item.get('detail_info', {}).get('overall_rating', '4.5'),
                    "bd_lat": loc['lat'], "bd_lng": loc['lng'], # 百度原始坐标(搜周边用)
                    "w_lat": w_lat, "w_lon": w_lon # 国际坐标(画图用)
                })
    except:
        pass
    return spots

def search_nearby_baidu(lat, lng, query, ak):
    session = requests.Session()
    session.trust_env = False
    
    url = "https://api.map.baidu.com/place/v2/search"
    # 周边搜索直接用百度坐标
    params = {"query": query, "location": f"{lat},{lng}", "radius": 1500, "output": "json", "ak": ak, "page_size": 3}
    
    res_str = "暂无周边记录"
    try:
        res = session.get(url, params=params).json()
        if res['status'] == 0 and res['results']:
            names = [i['name'] for i in res['results']]
            res_str = " | ".join(names)
    except: pass
    return res_str

# ====================
# 4. 主界面 UI
# ====================
st.title("🐼 百度地图全能旅游助手")

# --- 侧边栏 ---
with st.sidebar:
    st.header("🔑 系统设置")
    # 你的 AK (已填入)
    default_ak = "A2tnlcW3BrBa0QH22VLKo20SGTA1Pt7c"
    user_ak = st.text_input("百度地图 AK", value=default_ak, type="password")
    st.info("提示：此程序天气和地图数据均来自百度地图开放平台。")

# --- 顶部布局 ---
col_weather, col_control = st.columns([5, 5])

with col_control:
    st.subheader("📅 行程规划")
    c1, c2 = st.columns([1, 1])
    input_city = c1.text_input("目的地城市", "北京")
    start_date = c2.date_input("出发日期", datetime.date.today())
    
    # 最大的查询按钮
    if st.button("🚀 生成旅游方案", use_container_width=True):
        st.session_state.do_search = True
    else:
        st.session_state.do_search = False

# --- 核心逻辑 ---
if 'spots' not in st.session_state: st.session_state.spots = []
if 'weather' not in st.session_state: st.session_state.weather = []
if 'weather_src' not in st.session_state: st.session_state.weather_src = ""

# 执行搜索
if st.session_state.do_search and user_ak:
    with st.spinner(f"正在连接百度地图查询 {input_city} 的数据..."):
        # 1. 搜景点
        st.session_state.spots = search_spots_baidu("旅游景点", input_city, user_ak)
        st.session_state.sel_idx = 0
        
        # 2. 搜天气 (使用百度 API)
        w_data, src = get_baidu_weather(input_city, user_ak)
        st.session_state.weather = w_data
        st.session_state.weather_src = src
        
        if not st.session_state.spots:
            st.error("未找到相关景点，请检查城市名称或AK配额。")

# --- 显示天气 (左侧) ---
with col_weather:
    st.subheader(f"🌤️ {input_city} 天气")
    if st.session_state.weather:
        # 检查是否降级为模拟数据
        if "MOCK" in st.session_state.weather_src:
            st.warning("⚠️ 百度天气API权限未开通或调用失败，当前显示演示数据。")
        else:
            st.success("✅ 数据来源：百度地图 Weather API")

        # 使用列布局显示未来天气
        cols = st.columns(len(st.session_state.weather[:4])) # 只显示前4天
        for i, day in enumerate(st.session_state.weather[:4]):
            with cols[i]:
                st.markdown(f"""
                <div class="weather-card">
                    <div class="weather-date">{day['date']}</div>
                    <div class="weather-icon">{day['icon']}</div>
                    <div class="weather-temp">{day['temp']}</div>
                    <div class="weather-desc">{day['text']}</div>
                </div>
                """, unsafe_allow_html=True)
    else:
        st.info("等待生成方案...")

st.markdown("---")

# --- 显示地图与详情 (下方) ---
if st.session_state.spots:
    spots = st.session_state.spots
    
    st.header(f"📍 {input_city} 游玩路线推荐")
    
    # 1. 绘制地图
    # 使用第一个景点的坐标作为中心
    center_loc = [spots[0]['w_lat'], spots[0]['w_lon']]
    m = folium.Map(location=center_loc, zoom_start=12, tiles="CartoDB positron")
    
    route_line = []
    
    for i, s in enumerate(spots):
        pt = [s['w_lat'], s['w_lon']]
        route_line.append(pt)
        
        # 选中的景点标红，其他标蓝
        color = 'red' if i == st.session_state.get('sel_idx', 0) else 'blue'
        
        # 弹窗内容
        popup_html = f"<b>{i+1}. {s['name']}</b><br>评分: {s['score']}"
        folium.Marker(
            location=pt,
            popup=popup_html,
            tooltip=f"{i+1}. {s['name']}",
            icon=folium.Icon(color=color, icon="info-sign")
        ).add_to(m)
        
    # 画线
    if len(route_line) > 1:
        folium.PolyLine(route_line, color="#3498db", weight=4, opacity=0.8).add_to(m)
        
    st_folium(m, width=1400, height=500)
    
    st.caption("👆 蓝色路径为推荐游玩顺序")

    # 2. 交互详情区
    st.markdown("### 👇 景点详情 & 周边 (点击按钮切换)")
    
    # 动态生成按钮
    btn_cols = st.columns(len(spots))
    for i, s in enumerate(spots):
        # 按钮文字
        btn_label = f"{i+1}. {s['name'][:5]}.."
        if btn_cols[i].button(btn_label, key=f"spot_btn_{i}"):
            st.session_state.sel_idx = i
            st.rerun() # 刷新页面以更新地图高亮
            
    # 显示当前选中的景点详情
    curr = spots[st.session_state.get('sel_idx', 0)]
    
    with st.container():
        st.subheader(f"🚩 {curr['name']}")
        
        # 懒加载周边信息 (避免一次性消耗太多API配额)
        cache_key = f"nearby_{curr['name']}"
        if cache_key not in st.session_state:
            with st.spinner(f"正在查询 {curr['name']} 周边的美食和酒店..."):
                food = search_nearby_baidu(curr['bd_lat'], curr['bd_lng'], "美食", user_ak)
                hotel = search_nearby_baidu(curr['bd_lat'], curr['bd_lng'], "酒店", user_ak)
                st.session_state[cache_key] = (food, hotel)
                
        f_res, h_res = st.session_state[cache_key]
        
        c1, c2 = st.columns(2)
        with c1:
            st.info(f"🍜 **推荐美食**: {f_res}")
            st.write(f"📍 **地址**: {curr['addr']}")
        with c2:
            st.success(f"🏨 **周边住宿**: {h_res}")
            st.write(f"⭐ **百度评分**: {curr['score']}")
