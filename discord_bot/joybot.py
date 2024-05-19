import discord
import asyncio
import pymysql
import datetime
from datetime import timedelta
import random
from discord.ext import commands, tasks
from collections import Counter
import joybot_private

bot = commands.Bot(command_prefix='$')

token = joybot_private.joytoken
happyhost = joybot_private.happyhost
dbpsw = joybot_private.dbpsw

client =  discord.Client()
@bot.event
async def on_ready():
    print("================")
    print(bot.user.name)
    print(bot.user.id)
    print("================")

#커스텀명령어 삭제 명령어
@bot.command(name="삭제")
async def cmd_delete(ctx) :
    conn = pymysql.connect(happyhost, user='TT', password=dbpsw, db='Happy' ,charset = 'utf8')
    try:
        curs = conn.cursor()
        sql = "SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA = 'Happy'"
        curs.execute(sql)
        guild_cmd_table_id = str(curs.fetchall())
        conn.commit() 
    finally:
        conn.close()

    await ctx.send("명령어를 입력해 주세요.")
    #입력 대기
    def delete_check(m) :
        return m.content and m.author == ctx.author

    del_cmd = await bot.wait_for('message', check=delete_check)
    db_del_cmd = str("{.content}".format(del_cmd))
    try:
        guild_table_id = str(ctx.guild.id)
        if guild_table_id in guild_cmd_table_id :
            db_table_name = str("a_"+guild_table_id)

            qwer = pymysql.connect(happyhost, user='TT', password=dbpsw,db='Happy' ,charset = 'utf8')
            try:
                cursor = qwer.cursor(pymysql.cursors.DictCursor)
                sql1 = "select * from "+db_table_name+""
                cursor.execute(sql1)
                result = cursor.fetchall()
            finally:
                qwer.close()
        
            for i in result :
                if db_del_cmd == i.get('cmd')  :
                
                    conn = pymysql.connect(happyhost, user='TT', password=dbpsw,db='Happy' ,charset = 'utf8')
                    curs = conn.cursor()
                    sql = "delete from "+db_table_name+" where cmd = '"+db_del_cmd+"'"
                    curs.execute(sql)
                    conn.commit()
                    conn.close()
                    await ctx.send(db_del_cmd + "명령어가 삭제되었습니다.")
                    break

    except AttributeError:
        pass
#뉴비 역할 떼는 기능
@bot.command(name="늒네")
async def role_check(ctx) :
    nu_join = ctx.author.joined_at 
    nu_now = ctx.message.created_at
    nu_time = nu_now - nu_join
    nu_has_role = ctx.author.roles
    
    for i in nu_has_role :
        if i.name == '뉴비' and nu_time > datetime.timedelta(days=10) :
            await ctx.author.remove_roles(i)
            break
    if nu_time >datetime.timedelta(days=30) :
        await ctx.send("뉴비가 아니시네요")

#커스텀명령어 추가기능
@bot.command(name="추가")
async def cmd_add(ctx) :
    #DB연결
    conn = pymysql.connect(happyhost, user='TT', password=dbpsw, db='Happy' ,charset = 'utf8')
    try:
        curs = conn.cursor()
        sql = "SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA = 'Happy'"
        curs.execute(sql)
        guild_cmd_table_id = str(curs.fetchall())
        conn.commit() 
    finally:
        conn.close()
    
    try :
        guild_table_id = str(ctx.guild.id)
        if guild_table_id in guild_cmd_table_id :
            db_table_name = str("a_"+guild_table_id)
            await ctx.send("명령어를 입력해 주세요")
            
            def cmd_check(m):
                return m.content and  m.author == ctx.author

            guild_cmd = await bot.wait_for('message', check=cmd_check)
            str_guild_cmd = str("{.content}".format(guild_cmd))
            
            await ctx.send("컨텐츠를 입력해 주세요")
            
            def content_check(m):
                return m.content and m.author == ctx.author
            
            guild_content = await  bot.wait_for('message', check=content_check)
            str_guild_content =  str("{.content}".format(guild_content))

            conn = pymysql.connect(happyhost, user='TT', password=dbpsw,db='Happy' ,charset = 'utf8')
            curs = conn.cursor()
            sql = "INSERT into "+db_table_name+"(cmd, emoji) value (%s, %s)"
            curs.execute(sql, (str_guild_cmd, str_guild_content))
            conn.commit()
            conn.close()

            await ctx.send(str_guild_cmd+"가 추가되었습니다.")
    except AttributeError :
        pass 
#명령어 확인  기능
@bot.command(name="명령어확인")
async def cmd_list(ctx) :
    
    await ctx.send("👍이모지를 달면 다음페이지를 확인할수 있어요")
    conn = pymysql.connect(happyhost, user='TT', password=dbpsw, db='Happy' ,charset = 'utf8')
    try:
        curs = conn.cursor()
        sql = "SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA = 'Happy'"
        curs.execute(sql)
        guild_cmd_table_id = str(curs.fetchall())
        conn.commit() 
    finally:
        conn.close()
    #명령어 테이블 서버이름과 입력중인 서버이름 비교
    guild_table_id = str(ctx.guild.id)
    if guild_table_id in guild_cmd_table_id :
        db_table_name = str("a_"+guild_table_id)
        
        qwer = pymysql.connect(happyhost, user='TT', password=dbpsw,db='Happy' ,charset = 'utf8')
        try:
            cursor = qwer.cursor()
            sql1 = "select cmd from "+db_table_name+""
            cursor.execute(sql1)
            result = cursor.fetchall()
        finally:
            qwer.close()
        result = list(result)
        cmd_len = len(result)
        cmd_page =int(cmd_len // 10)
        page = []
        print(cmd_page)
        if cmd_page > 1 :
            i = 0
            while(i<cmd_page):
                page.append(str(','.join(result[i*10:((i+1)*10)+19])))
                i += 1
            page.append(result[i:])
        else :
            page.append(result)


        cmd_list_embed = discord.Embed()
        cmd_list_embed.add_field(name="명령어 목록", value=page[0]) 
        qwer = await ctx.send(embed=  cmd_list_embed)

        def reaction_check(reaction, user) :
            return str(reaction.emoji) == '👍' and user ==  ctx.author
        page_cnt =0
        for i in page :
            try:
                check_reaction = await bot.wait_for('reaction_add',timeout=20 ,check=reaction_check) 

            except asyncio.TimeoutError:
                break
            
            emoji = str("{0}".format(check_reaction))
            
            if '👍' in emoji:
                cmd_list_embed_page = discord.Embed()
                cmd_list_embed_page.add_field(name="명령어 목록", value=i)
                cmd_list_embed_page.set_footer(text=""+page_cnt+"페이지 입니다.")
                await qwer.edit(embed = cmd_list_embed_page)
                await qwer.clear_reactions()
                page_cnt += 1
            
        
async def um_message(message) :
    if message.author.bot :
        return None

    conn = pymysql.connect(happyhost, user='TT', password=dbpsw, db='Happy' ,charset = 'utf8')
    try:
        curs = conn.cursor()
        sql = "SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA = 'Happy'"
        curs.execute(sql)
        guild_cmd_table_id = str(curs.fetchall())
        conn.commit() 
    finally:
        conn.close()

    guild_table_id = str(message.guild.id)
    if guild_table_id in guild_cmd_table_id :
        db_table_name = str("a_"+guild_table_id)

        qwer = pymysql.connect(happyhost, user='TT', password=dbpsw,db='Happy' ,charset = 'utf8')
        try:
            cursor = qwer.cursor(pymysql.cursors.DictCursor)
            sql1 = "select * from "+db_table_name+""
            cursor.execute(sql1)
            result = cursor.fetchall()
        finally:
            qwer.close()
        
        for i in result :
            if message.content == i.get('cmd') :
                guild_emoji = i.get('emoji')
                if 'https' in guild_emoji :
                    embed = discord.Embed()
                    embed.set_image(url=guild_emoji)
                    await message.channel.send(embed=embed)
                    break
                
                if 'http' in guild_emoji  :
                    embed = discord.Embed()
                    embed.set_image(url=guild_emoji)
                    await message.channel.send(embed=embed)
                    break

                await message.channel.send(guild_emoji)

bot.add_listener(um_message,'on_message')
    

bot.run(token)