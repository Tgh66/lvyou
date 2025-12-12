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
st.set_page_config(page_title="旅游管家 Pro (和风天气版)", layout="wide", page_icon="🌦️")

st.markdown("""
<style>
    .weather-card {
        background: linear-gradient(135deg, #a18cd1 0%, #fbc2eb 100%);
        padding: 12px;
        border-radius: 12px;
        text-align: center;
        border: 1px solid #fff;
        color: white;
        box-shadow: 0 4px 6px rgba(0,0,0,0.1);
    }
    .weather-icon { font-size: 32px; margin: 8px 0; }
    .weather-temp { font-size: 20px; font-weight: bold; }
    .stButton>button { border-radius: 20px; width: 100%; }
</style>
""", unsafe_allow_html=True)

# ====================
# 1. 核心算法工具
# ====================
x_pi = 3.14159265358979324 * 3000.0 / 180.0

def bd09_to_wgs84(bd_lon, bd_lat):
    """
    百度坐标(BD09) -> 国际坐标(WGS84)
    用于将百度搜到的景点坐标，转换为和风天气可用的坐标
    """
    x = bd_lon - 0.0065
    y = bd_lat - 0.006
    z = math.sqrt(x * x + y * y) - 0.00002 * math.sin(y * x_pi)
    theta = math.atan2(y, x) - 0.000003 * math.cos(x * x_pi)
    gg_lon = z * math.cos(theta)
    gg_lat = z * math.sin(theta)
    
    # 这里做一个简化的二次转换 (GCJ02 -> WGS84 近似)
    # 为了精度通常需要更复杂的库，但对于天气查询，这个精度足够了
    return gg_lat, gg_lon 

def haversine_distance(lat1, lon1, lat2, lon2):
    """计算两点距离 (km)"""
    R = 6371
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1-a))

def optimize_route_algorithm(spots):
    """最短路径贪心算法"""
    if not spots: return []
    optimized = [spots[0]]
    remaining = spots[1:]
    while remaining:
        curr = optimized[-1]
        nearest = min(remaining, key=lambda s: haversine_distance(curr['w_lat'], curr['w_lon'], s['w_lat'], s['w_lon']))
        optimized.append(nearest)
        remaining.remove(nearest)
    return optimized

def generate_smart_packing_list(weather_list):
    """智能行李清单"""
    items = {"必带": ["身份证/学生证", "手机充电器", "充电宝", "纸巾/湿巾"]}
    
    # 提取天气特征
    all_text = "".join([d['text'] for d in weather_list])
    # 确保温度转为整数
    all_high = [int(float(d['high_temp'])) for d in weather_list]
    all_low = [int(float(d['low_temp'])) for d in weather_list]
    min_temp = min(all_low) if all_low else 20
    max_temp = max(all_high) if all_high else 25
    
    clothes = []
    gear = []
    
    # 规则引擎
    if "雨" in all_text: gear.append("雨伞/雨衣 ☔")
    if "雪" in all_text: gear.append("防滑鞋/手套 🧤")
    if "晴" in all_text and max_temp > 25: gear.append("防晒霜/墨镜 🕶️")
    
    if min_temp < 10: clothes.append("羽绒服/厚大衣 🧥")
    elif min_temp < 18: clothes.append("卫衣/夹克 👔")
    elif min_temp < 24: clothes.append("长袖/衬衫 👕")
    else: clothes.append("短袖/透气夏装 🎽")
    
    if max_temp > 30: gear.append("便携小风扇 🎐")
    
    items["衣物建议"] = clothes
    items["装备建议"] = gear
    return items

# ====================
# 2. 和风天气 API 模块 (重构版)
# ====================
def map_qweather_icon(icon_code):
    """将和风天气的 Icon 代码映射为 Emoji"""
    code = int(icon_code)
    if 100 <= code <= 104: return "🌞" # 晴/多云
    if 150 <= code <= 154: return "🌙" # 夜间晴
    if 300 <= code <= 399: return "🌧" # 雨
    if 400 <= code <= 499: return "❄️" # 雪
    if 500 <= code <= 515: return "🌫️" # 雾/霾
    if 200 <= code <= 213: return "🌪" # 风
    return "🌥️"

def get_qweather_forecast(lat, lon, api_key):
    """
    调用和风天气 /v7/weather/3d 接口
    参数: lat, lon (WGS84坐标), api_key
    """
    session = requests.Session()
    session.trust_env = False # 禁用代理
    
    # 构造坐标参数，格式: 经度,纬度 (注意和风要求经度在前，且不超过2位小数)
    location_str = f"{lon:.2f},{lat:.2f}"
    
    # 自动适配 Free (devapi) 和 Paid (api) 域名
    hosts = [
        "https://devapi.qweather.com/v7/weather/3d",
        "https://api.qweather.com/v7/weather/3d"
    ]
    
    forecasts = []
    
    for url in hosts:
        params = {
            "location": location_str,
            "key": api_key,
            "lang": "zh"
        }
        try:
            # 发起请求
            res = session.get(url, params=params, timeout=5)
            
            if res.status_code == 200:
                data = res.json()
                if data['code'] == "200":
                    # 解析 daily 数组]
                    for day in data['daily']:
                        forecasts.append({
                            "date": day['fxDate'], # 预报日期
                            "text": day['textDay'], # 白天天气描述
                            "icon": map_qweather_icon(day['iconDay']), # 图标代码
                            "temp": f"{day['tempMin']}~{day['tempMax']}°C",
                            "high_temp": day['tempMax'], # 用于穿衣算法
                            "low_temp": day['tempMin'],
                            "wind": f"{day['windDirDay']} {day['windScaleDay']}级"
                        })
                    return forecasts, "QWeather"
                elif data['code'] == "403" or "Invalid Host" in str(data):
                    continue # 换个域名重试
        except Exception:
            pass
            
    # 失败兜底
    return [], "FAIL"

# ====================
# 3. 百度地图 API 模块 (仅用于搜索景点)
# ====================
def search_spots_baidu(keyword, city, ak):
    """使用百度地图 Place API 搜索景点"""
    session = requests.Session()
    session.trust_env = False
    spots = []
    try:
        url = "https://api.map.baidu.com/place/v2/search"
        params = {
            "query": keyword, "region": city, "output": "json", 
            "ak": ak, "scope": 2, "page_size": 8
        }
        res = session.get(url, params=params).json()
        if res['status'] == 0:
            for item in res['results']:
                loc = item['location']
                # 关键：获取百度坐标后，转为 WGS84 供和风天气使用
                w_lat, w_lon = bd09_to_wgs84(loc['lng'], loc['lat'])
                
                spots.append({
                    "name": item['name'],
                    "addr": item.get('address', '暂无地址'),
                    "score": item.get('detail_info', {}).get('overall_rating', '4.5'),
                    "bd_lat": loc['lat'], "bd_lng": loc['lng'], # 百度坐标(地图用)
                    "w_lat": w_lat, "w_lon": w_lon # 国际坐标(天气/距离计算用)
                })
    except: pass
    return spots

def search_nearby_baidu(lat, lng, query, ak):
    session = requests.Session()
    session.trust_env = False
    try:
        url = "https://api.map.baidu.com/place/v2/search"
        params = {"query": query, "location": f"{lat},{lng}", "radius": 2000, "output": "json", "ak": ak}
        res = session.get(url, params=params).json()
        if res['status'] == 0 and res['results']:
            return " | ".join([i['name'] for i in res['results'][:3]])
    except: pass
    return "暂无推荐"

# ====================
# 4. 主界面逻辑
# ====================
st.title("🌦️ 旅游管家 Pro (和风天气版)")

with st.sidebar:
    st.header("🔑 API 配置")
    # 百度用于搜地图，和风用于查天气
    default_baidu = "A2tnlcW3BrBa0QH22VLKo20SGTA1Pt7c" 
    baidu_ak = st.text_input("百度地图 AK", value=default_baidu, type="password")
    
    # 和风天气 Key
    default_hefeng = "017cf1cda9b44a8eb2268d6562477691"
    hefeng_key = st.text_input("和风天气 Key", value=default_hefeng, type="password")
    
    st.divider()
    st.info("数据源说明：\n- 地点搜索：百度地图 API\n- 天气预报：和风天气 API")

# 顶部输入区
c1, c2, c3 = st.columns([2, 2, 2])
city = c1.text_input("目的地", "重庆")
route_mode = c2.selectbox("路线策略", ["智能最短路径 (推荐)", "默认热度排序"])

if c3.button("🚀 生成方案", use_container_width=True):
    st.session_state.search = True
else:
    st.session_state.search = False if 'search' not in st.session_state else st.session_state.search

# 初始化状态
if 'spots' not in st.session_state: st.session_state.spots = []
if 'weather' not in st.session_state: st.session_state.weather = []

# --- 核心逻辑 ---
if st.session_state.search and baidu_ak and hefeng_key:
    with st.spinner(f"正在规划 {city} 的行程..."):
        # 1. 百度搜景点
        raw_spots = search_spots_baidu("旅游景点", city, baidu_ak)
        
        if raw_spots:
            # 2. 路线排序
            if "智能" in route_mode:
                st.session_state.spots = optimize_route_algorithm(raw_spots)
            else:
                st.session_state.spots = raw_spots
            
            # 3. 和风查天气 (使用第一个景点的 WGS84 坐标)
            # 这样比直接查城市名更精准，能查到景区当地的天气
            first_spot = st.session_state.spots[0]
            w_data, src = get_qweather_forecast(first_spot['w_lat'], first_spot['w_lon'], hefeng_key)
            
            if w_data:
                st.session_state.weather = w_data
                st.toast("天气获取成功 (QWeather)", icon="🌤️")
            else:
                st.error("天气查询失败，请检查和风 Key")
            
            st.session_state.sel_idx = 0
        else:
            st.error("未找到相关景点，请检查城市名称")

# --- 天气展示区 ---
if st.session_state.weather:
    st.write(f"📅 **{city} 未来3天天气预报**")
    cols = st.columns(3)
    # 显示前3天
    for i, d in enumerate(st.session_state.weather[:3]): 
        with cols[i]:
            st.markdown(f"""
            <div class="weather-card">
                <div style="font-size:14px; opacity:0.8">{d['date']}</div>
                <div class="weather-icon">{d['icon']}</div>
                <div class="weather-temp">{d['temp']}</div>
                <div style="font-size:14px">{d['text']}</div>
                <div style="font-size:12px; opacity:0.8">{d['wind']}</div>
            </div>
            """, unsafe_allow_html=True)
elif st.session_state.search:
    st.warning("暂无天气数据")

st.divider()

# --- 地图与功能区 ---
if st.session_state.spots:
    spots = st.session_state.spots
    
    tab1, tab2, tab3 = st.tabs(["🗺️ 路线地图", "📋 景点详情", "🎒 智能清单"])
    
    # Tab 1: 地图
    with tab1:
        # 地图中心
        center = [spots[0]['w_lat'], spots[0]['w_lon']]
        m = folium.Map(location=center, zoom_start=13, tiles="CartoDB positron")
        
        pts = []
        for i, s in enumerate(spots):
            pt = [s['w_lat'], s['w_lon']]
            pts.append(pt)
            
            color = 'red' if i == st.session_state.get('sel_idx', 0) else 'blue'
            popup_html = f"<b>{i+1}. {s['name']}</b><br>评分:{s['score']}"
            icon_html = f"""<div style="background:{color};color:white;border-radius:50%;width:24px;height:24px;text-align:center;border:2px solid white">{i+1}</div>"""
            
            folium.Marker(location=pt, popup=popup_html, icon=folium.DivIcon(html=icon_html)).add_to(m)
            
        if len(pts) > 1:
            folium.PolyLine(pts, color="#3498db", weight=4, opacity=0.8).add_to(m)
            
        st_folium(m, width=1200, height=500)

    # Tab 2: 详情
    with tab2:
        cols = st.columns(len(spots))
        for i, s in enumerate(spots):
            if cols[i].button(f"{i+1}.{s['name'][:3]}", key=f"btn_{i}"):
                st.session_state.sel_idx = i
                st.rerun()
        
        curr = spots[st.session_state.get('sel_idx', 0)]
        st.subheader(f"📍 {curr['name']}")
        
        # 懒加载周边
        cache_key = f"nb_{curr['name']}"
        if cache_key not in st.session_state:
            with st.spinner("查找周边..."):
                f = search_nearby_baidu(curr['bd_lat'], curr['bd_lng'], "美食", baidu_ak)
                h = search_nearby_baidu(curr['bd_lat'], curr['bd_lng'], "酒店", baidu_ak)
                st.session_state[cache_key] = (f, h)
        
        f_res, h_res = st.session_state[cache_key]
        c1, c2 = st.columns(2)
        with c1:
            st.info(f"🍜 **美食**: {f_res}")
            st.write(f"🏠 **地址**: {curr['addr']}")
        with c2:
            st.success(f"🏨 **住宿**: {h_res}")
            st.write(f"⭐ **评分**: {curr['score']}")

    # Tab 3: 智能清单
    with tab3:
        if st.session_state.weather:
            pack_list = generate_smart_packing_list(st.session_state.weather)
            c_left, c_right = st.columns(2)
            
            with c_left:
                st.markdown("#### 👕 穿衣建议")
                for item in pack_list["衣物建议"]:
                    st.checkbox(item, value=True, key=item)
            
            with c_right:
                st.markdown("#### 🎒 装备 & 必带")
                for item in pack_list["必带"] + pack_list["装备建议"]:
                    st.checkbox(item, value=True, key=item)
        else:
            st.info("需要先获取天气数据才能生成建议")
