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
st.set_page_config(page_title="百度全能旅游助手 (智能路线版)", layout="wide", page_icon="🚗")

st.markdown("""
<style>
    .weather-card {
        background: linear-gradient(120deg, #fdfbfb 0%, #ebedee 100%);
        padding: 12px;
        border-radius: 12px;
        text-align: center;
        color: #2c3e50;
        box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        margin-bottom: 10px;
        border: 1px solid #ddd;
    }
    .weather-date { font-size: 14px; color: #666; }
    .weather-icon { font-size: 32px; margin: 5px 0; }
    .weather-temp { font-size: 20px; font-weight: bold; color: #e65100; }
    .weather-desc { font-size: 15px; font-weight: 500; }
    .stButton>button { border-radius: 20px; width: 100%; }
</style>
""", unsafe_allow_html=True)

# ====================
# 1. 算法核心工具 (新增部分)
# ====================
x_pi = 3.14159265358979324 * 3000.0 / 180.0

def bd09_to_wgs84(bd_lon, bd_lat):
    """百度坐标系(BD09) 转 WGS84"""
    x = bd_lon - 0.0065
    y = bd_lat - 0.006
    z = math.sqrt(x * x + y * y) - 0.00002 * math.sin(y * x_pi)
    theta = math.atan2(y, x) - 0.000003 * math.cos(x * x_pi)
    gg_lon = z * math.cos(theta)
    gg_lat = z * math.sin(theta)
    return gg_lat, gg_lon

def haversine_distance(lat1, lon1, lat2, lon2):
    """
    计算两点间的球面距离 (单位: km)
    用于路径优化算法
    """
    R = 6371  # 地球半径
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2)**2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))

def optimize_route_algorithm(spots):
    """
    【贪心算法】最近邻路径规划
    目标：最短距离 / 节省时间
    """
    if not spots:
        return []
    
    # 1. 以列表中的第一个景点（通常是最热门的）作为起点
    optimized_spots = [spots[0]]
    remaining_spots = spots[1:]
    
    # 2. 循环查找最近的下一个点
    while remaining_spots:
        current_spot = optimized_spots[-1]
        
        # 在剩余景点中找到距离当前景点最近的一个
        nearest_spot = min(
            remaining_spots, 
            key=lambda s: haversine_distance(
                current_spot['w_lat'], current_spot['w_lon'],
                s['w_lat'], s['w_lon']
            )
        )
        
        # 加入路径并从剩余列表中移除
        optimized_spots.append(nearest_spot)
        remaining_spots.remove(nearest_spot)
        
    return optimized_spots

# ====================
# 2. 百度 API 模块
# ====================
def get_baidu_weather(city_name, ak):
    session = requests.Session()
    session.trust_env = False
    forecasts = []
    try:
        # Step 1: 找坐标
        geo_url = "https://api.map.baidu.com/place/v2/search"
        geo_params = {"query": city_name, "region": city_name, "output": "json", "ak": ak, "page_size": 1}
        geo_res = session.get(geo_url, params=geo_params).json()
        if geo_res['status'] != 0 or not geo_res['results']: return get_mock_weather(), "MOCK"
        location = geo_res['results'][0]['location']
        
        # Step 2: 找区号
        reg_url = "https://api.map.baidu.com/reverse_geocoding/v3/"
        reg_params = {"ak": ak, "output": "json", "coordtype": "bd09ll", "location": f"{location['lat']},{location['lng']}"}
        reg_res = session.get(reg_url, params=reg_params).json()
        district_id = reg_res['result']['addressComponent']['adcode']
        
        # Step 3: 查天气
        weather_url = "https://api.map.baidu.com/weather/v1/"
        weather_params = {"district_id": district_id, "data_type": "all", "ak": ak}
        w_res = session.get(weather_url, params=weather_params).json()
        
        if w_res['status'] == 0:
            for day in w_res['result']['forecasts']:
                text = day['text_day']
                icon = "🌥️"
                if "晴" in text: icon = "🌞"
                elif "云" in text or "阴" in text: icon = "⛅"
                elif "雨" in text: icon = "🌧"
                elif "雪" in text: icon = "❄️"
                forecasts.append({
                    "date": f"{day['date']} {day['week']}",
                    "icon": icon,
                    "text": f"{day['text_day']} | {day['wind_dir_day']}",
                    "temp": f"{day['low']}°~{day['high']}°C"
                })
            return forecasts, "BAIDU"
    except: pass
    return get_mock_weather(), "MOCK"

def get_mock_weather():
    mock = []
    base = datetime.date.today()
    for i in range(4):
        d = base + datetime.timedelta(days=i)
        t = random.randint(18, 28)
        mock.append({"date": d.strftime("%Y-%m-%d"), "icon": "⛅", "text": "多云", "temp": f"{t-5}°~{t}°C"})
    return mock

def search_spots_baidu(keyword, city, ak):
    session = requests.Session()
    session.trust_env = False
    url = "https://api.map.baidu.com/place/v2/search"
    # 这里增加了 page_size 到 10，让算法有更多选择空间
    params = {"query": keyword, "region": city, "output": "json", "ak": ak, "scope": 2, "page_size": 10}
    spots = []
    try:
        res = session.get(url, params=params).json()
        if res['status'] == 0:
            for item in res['results']:
                loc = item['location']
                w_lat, w_lon = bd09_to_wgs84(loc['lng'], loc['lat'])
                spots.append({
                    "name": item['name'],
                    "addr": item.get('address', '无地址'),
                    "score": item.get('detail_info', {}).get('overall_rating', '4.5'),
                    "bd_lat": loc['lat'], "bd_lng": loc['lng'],
                    "w_lat": w_lat, "w_lon": w_lon
                })
    except: pass
    return spots

def search_nearby_baidu(lat, lng, query, ak):
    session = requests.Session()
    session.trust_env = False
    url = "https://api.map.baidu.com/place/v2/search"
    params = {"query": query, "location": f"{lat},{lng}", "radius": 1500, "output": "json", "ak": ak, "page_size": 3}
    try:
        res = session.get(url, params=params).json()
        if res['status'] == 0 and res['results']:
            return " | ".join([i['name'] for i in res['results']])
    except: pass
    return "暂无推荐"

# ====================
# 3. 页面主逻辑
# ====================
st.title("🚗 智能旅游规划师 (路线优化版)")

with st.sidebar:
    st.header("🔑 设置")
    default_ak = "A2tnlcW3BrBa0QH22VLKo20SGTA1Pt7c"
    user_ak = st.text_input("百度 AK", value=default_ak, type="password")
    
    st.markdown("---")
    st.header("🛠️ 路线偏好")
    # 新增：让用户选择是否优化
    route_mode = st.radio("规划策略", ["智能最短路径 (推荐)", "百度默认排序"])

col_weather, col_control = st.columns([5, 5])

with col_control:
    st.subheader("📅 行程输入")
    c1, c2 = st.columns(2)
    city = c1.text_input("目的地", "西安")
    date = c2.date_input("出发日期", datetime.date.today())
    
    if st.button("🚀 生成优化方案", use_container_width=True):
        st.session_state.search = True
    else:
        st.session_state.search = False

if 'spots' not in st.session_state: st.session_state.spots = []
if 'weather' not in st.session_state: st.session_state.weather = []

if st.session_state.search and user_ak:
    with st.spinner("正在搜索景点并进行路径计算..."):
        # 1. 原始搜索
        raw_spots = search_spots_baidu("旅游景点", city, user_ak)
        
        if raw_spots:
            # 2. 核心算法：路径优化
            if "智能" in route_mode:
                st.session_state.spots = optimize_route_algorithm(raw_spots)
                st.toast("✅ 已为您规划最短游玩路线！", icon="🗺️")
            else:
                st.session_state.spots = raw_spots
            
            # 3. 查天气
            w, _ = get_baidu_weather(city, user_ak)
            st.session_state.weather = w
            st.session_state.sel_idx = 0
        else:
            st.error("未找到景点")

# 天气展示
with col_weather:
    st.subheader(f"🌤️ {city} 天气")
    if st.session_state.weather:
        cols = st.columns(4)
        for i, d in enumerate(st.session_state.weather[:4]):
            with cols[i]:
                st.markdown(f"""
                <div class="weather-card">
                    <div class="weather-date">{d['date']}</div>
                    <div class="weather-icon">{d['icon']}</div>
                    <div class="weather-temp">{d['temp']}</div>
                    <div class="weather-desc">{d['text']}</div>
                </div>""", unsafe_allow_html=True)
    else:
        st.info("请点击生成方案")

st.markdown("---")

# 地图展示
if st.session_state.spots:
    spots = st.session_state.spots
    st.header(f"📍 {city} 游玩路线图 ({route_mode})")
    
    # 计算地图中心
    center = [spots[0]['w_lat'], spots[0]['w_lon']]
    m = folium.Map(location=center, zoom_start=13, tiles="CartoDB positron")
    
    route_coords = []
    
    for i, s in enumerate(spots):
        pt = [s['w_lat'], s['w_lon']]
        route_coords.append(pt)
        
        color = 'red' if i == st.session_state.get('sel_idx', 0) else 'blue'
        
        # 序号标记
        icon_html = f"""
            <div style="font-family: sans-serif; color: white; background-color: {color}; 
            border-radius: 50%; width: 24px; height: 24px; display: flex; 
            justify_content: center; align-items: center; border: 2px solid white;">
            {i+1}
            </div>"""
        
        folium.Marker(
            location=pt,
            popup=s['name'],
            icon=folium.DivIcon(html=icon_html),
            tooltip=f"第{i+1}站: {s['name']}"
        ).add_to(m)
    
    # 绘制带箭头的线
    if len(route_coords) > 1:
        folium.PolyLine(
            route_coords, 
            color="#3498db", 
            weight=5, 
            opacity=0.8,
            tooltip="推荐行进路线"
        ).add_to(m)
    
    st_folium(m, width=1400, height=500)
    
    # 距离概算
    total_dist = 0
    for i in range(len(spots)-1):
        total_dist += haversine_distance(
            spots[i]['w_lat'], spots[i]['w_lon'], 
            spots[i+1]['w_lat'], spots[i+1]['w_lon']
        )
    st.caption(f"📏 预计路线总直线距离: **{total_dist:.1f} km** (不含路况绕行)")

    # 详情区
    st.markdown("### 👇 景点详情 (点击查看周边)")
    cols = st.columns(len(spots))
    for i, s in enumerate(spots):
        if cols[i].button(f"{i+1}. {s['name'][:4]}", key=f"b_{i}"):
            st.session_state.sel_idx = i
            st.rerun()
            
    curr = spots[st.session_state.get('sel_idx', 0)]
    with st.container():
        st.subheader(f"🚩 第 {st.session_state.get('sel_idx', 0)+1} 站: {curr['name']}")
        
        cache = f"nb_{curr['name']}"
        if cache not in st.session_state:
            with st.spinner("查找周边..."):
                f = search_nearby_baidu(curr['bd_lat'], curr['bd_lng'], "美食", user_ak)
                h = search_nearby_baidu(curr['bd_lat'], curr['bd_lng'], "酒店", user_ak)
                st.session_state[cache] = (f, h)
        
        f_res, h_res = st.session_state[cache]
        c1, c2 = st.columns(2)
        with c1:
            st.info(f"🍜 **美食**: {f_res}")
            st.write(f"📍 **地址**: {curr['addr']}")
        with c2:
            st.success(f"🏨 **住宿**: {h_res}")
            st.write(f"⭐ **评分**: {curr['score']}")
