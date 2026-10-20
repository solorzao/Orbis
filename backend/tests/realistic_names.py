"""Real given names, surnames, public figures and organisations, for search fixtures.

Written from general knowledge, not downloaded: common names across cultures,
so combined names share word-start trigrams the way GDELT's do ("Su..." in
Susan, Sunil, Sullivan, Suzuki; "Mo..." in Mohammed, Morgan, Moore). Public
figures and organisations are the names people search for.
"""

from __future__ import annotations

GIVEN_NAMES = """
James John Robert Michael William David Richard Joseph Thomas Charles Christopher Daniel
Matthew Anthony Mark Donald Steven Paul Andrew Joshua Kenneth Kevin Brian George Timothy
Ronald Edward Jason Jeffrey Ryan Jacob Gary Nicholas Eric Jonathan Stephen Larry Justin
Scott Brandon Benjamin Samuel Gregory Alexander Frank Patrick Raymond Jack Dennis Jerry
Tyler Aaron Adam Nathan Henry Douglas Zachary Peter Kyle Noah Ethan Jeremy Walter Keith
Roger Terry Austin Sean Gerald Carl Harold Dylan Arthur Lawrence Jordan Jesse Bryan Billy
Bruce Gabriel Joe Logan Alan Albert Willie Elijah Wayne Randy Vincent Mason Roy Ralph
Bobby Russell Bradley Philip Eugene Bill Harry Hunter Mary Patricia Jennifer Linda
Elizabeth Barbara Susan Jessica Sarah Karen Lisa Nancy Betty Sandra Margaret Ashley
Kimberly Emily Donna Michelle Carol Amanda Melissa Deborah Stephanie Dorothy Rebecca
Sharon Laura Cynthia Amy Kathleen Angela Shirley Brenda Emma Anna Pamela Nicole Samantha
Katherine Christine Helen Debra Rachel Carolyn Janet Maria Catherine Heather Diane Olivia
Julie Joyce Victoria Ruth Virginia Lauren Kelly Christina Joan Evelyn Judith Andrea
Hannah Megan Cheryl Jacqueline Martha Madison Teresa Gloria Sara Janice Ann Kathryn
Abigail Sophia Frances Jean Alice Judy Isabella Julia Grace Amber Denise Danielle
Marilyn Beverly Charlotte Natalie Theresa Diana Doris Kayla Alexis Marie
Mohammed Mohamed Mohammad Muhammad Ahmed Ahmad Ali Hassan Hussein Hamid Hamza Hamad
Khalid Omar Umar Yusuf Youssef Ibrahim Ismail Mustafa Mahmoud Abdullah Abdul Abdel
Rashid Said Saeed Salim Samir Tariq Walid Karim Nabil Fatima Aisha Mariam Maryam Leila
Layla Zainab Amina Huda Noor Rania Yasmin Bilal Faisal Jamal Nasser Majid Sultan
Suleiman Sulaiman Haider Habib Hani Hisham Hamdi Hana Hamida Sunil Sunita Suresh Sanjay
Rajesh Ramesh Rahul Amit Anil Vijay Ravi Arjun Deepak Manoj Mukesh Narendra Nitin
Pradeep Prakash Rakesh Sachin Sandeep Shiv Vikram Vinod Ashok Priya Pooja Anita Kavita
Neha Deepika Lakshmi Meena Rekha Shanti Sunny Sundar Subhash Sudhir Sumit Suraj Sushil
Imran Nawaz Shehbaz Asif Bilawal Arvind Amitabh Mamata Wei Jun Hui Ming Xiaoming Jing
Hiroshi Takashi Kenji Yuki Haruto Sakura Yuko Akira Minjun Jihoon Seoyeon Hyun Jae Sung
Minh Anh Hoang Duc Linh Carlos Luis Jorge Miguel Javier Alejandro Fernando Pedro Pablo
Diego Manuel Francisco Antonio Rafael Sergio Andres Ricardo Eduardo Roberto Mario
Gustavo Lucia Carmen Isabel Elena Rosa Ana Sofia Valentina Camila Gabriela Mariana
Paula Daniela Claudia Hans Klaus Jurgen Wolfgang Stefan Andreas Markus Matthias Pierre
Francois Nicolas Emmanuel Olivier Philippe Louis Antoine Giuseppe Giovanni Marco Luca
Matteo Alessandro Francesco Giorgia Chiara Giulia Sergei Vladimir Dmitry Alexei Ivan
Mikhail Nikolai Andrei Olga Tatiana Natalia Svetlana Volodymyr Oleksandr Olena Piotr
Tomasz Krzysztof Jan Lars Erik Anders Sven Ingrid Astrid Mehmet Murat Emre Burak Ayse
Fatma Kwame Kofi Chinedu Emeka Oluwaseun Tunde Ngozi Amaka Musa Moses Thabo Sipho
Nelson Yoweri Bola Yair Naftali Isaac Moshe Yossi Avi Itamar Yoav Benny Gideon Shira
Noa Tamar Monica Mona Morgan Murray Muriel Bishop Bianca Birgit Sunniva Hamish Hamilton
""".split()

SURNAMES = """
Smith Johnson Williams Brown Jones Garcia Miller Davis Rodriguez Martinez Hernandez
Lopez Gonzalez Wilson Anderson Thomas Taylor Moore Jackson Martin Lee Perez Thompson
White Harris Sanchez Clark Ramirez Lewis Robinson Walker Young Allen King Wright Scott
Torres Nguyen Hill Flores Green Adams Nelson Baker Hall Rivera Campbell Mitchell Carter
Roberts Gomez Phillips Evans Turner Diaz Parker Cruz Edwards Collins Reyes Stewart
Morris Morales Murphy Cook Rogers Gutierrez Ortiz Morgan Cooper Peterson Bailey Reed
Kelly Howard Ramos Kim Cox Ward Richardson Watson Brooks Chavez Wood James Bennett Gray
Mendoza Ruiz Hughes Price Alvarez Castillo Sanders Patel Myers Long Ross Foster Jimenez
Powell Jenkins Perry Russell Sullivan Bell Coleman Butler Henderson Barnes Gonzales
Fisher Vasquez Simmons Romero Jordan Patterson Alexander Hamilton Graham Reynolds
Griffin Wallace Moreno West Cole Hayes Bryant Herrera Gibson Ellis Tran Medina Aguilar
Stevens Murray Ford Castro Marshall Owens Harrison Fernandez McDonald Woods Washington
Kennedy Wells Vargas Henry Chen Freeman Webb Tucker Guzman Burns Crawford Olson Simpson
Porter Hunter Gordon Mendez Silva Shaw Snyder Mason Dixon Munoz Hunt Hicks Holmes Palmer
Wagner Black Robertson Boyd Rose Stone Salazar Fox Warren Mills Meyer Rice Schmidt Garza
Daniels Ferguson Nichols Stephens Soto Weaver Ryan Gardner Payne Grant Dunn Spencer
Hawkins Arnold Pierce Hansen Peters Santos Hart Bradley Knight Elliott Cunningham
Duncan Armstrong Hudson Carroll Lane Riley Andrews Ray Delgado Berry Perkins Hoffman
Johnston Matthews Richards Willis Carpenter Lawrence Sandoval Bishop Hassan Hussein Ali
Ahmed Mohamed Khan Abbas Haddad Khalil Mansour Nasser Saleh Hamdan Qasim Rahman
Siddiqui Hashemi Hamadi Hamid Habib Masri Sultani Suleiman Sabbagh Shamsi Bakr Darwish
Farouk Ghanem Jaber Karam Mahfouz Mubarak Nour Osman Othman Qureshi Saad Sharif Taha
Yassin Zaki Sharma Singh Kumar Gupta Shah Mehta Joshi Iyer Reddy Nair Rao Das Bose
Chatterjee Banerjee Mukherjee Verma Yadav Mishra Pandey Tiwari Agarwal Malhotra Kapoor
Chopra Khanna Bhatia Sinha Saxena Sundaram Subramanian Suri Sood Sethi Hussain
Chaudhry Malik Butt Sheikh Wang Li Zhang Liu Yang Huang Zhao Wu Zhou Xu Sun Ma Zhu Hu
Guo He Lin Luo Gao Tanaka Suzuki Takahashi Watanabe Ito Yamamoto Nakamura Kobayashi
Kato Yoshida Sato Park Choi Jung Kang Cho Yoon Jang Lim Han Pham Hoang Phan Vu Dang Bui
Ngo Muller Schneider Weber Becker Schulz Koch Bauer Richter Klein Wolf Schroder Neumann
Schwarz Zimmermann Braun Bernard Dubois Petit Durand Leroy Moreau Simon Laurent
Lefebvre Michel Rossi Russo Ferrari Esposito Bianchi Romano Colombo Ricci Marino Greco
Bruno Gallo Conti Ivanov Smirnov Kuznetsov Popov Sokolov Lebedev Kozlov Novikov Morozov
Petrov Volkov Shevchenko Kovalenko Bondarenko Tkachenko Nowak Kowalski Wisniewski Wojcik
Jensen Nielsen Pedersen Andersen Johansson Karlsson Nilsson Eriksson Larsson Yilmaz
Kaya Demir Sahin Celik Yildiz Ozturk Aydin Arslan Dogan Okafor Okonkwo Adeyemi Oluwole
Abubakar Bello Ibrahim Mensah Owusu Boateng Asante Kamau Otieno Mwangi Ochieng Ndlovu
Dlamini Nkosi Zulu Mokoena Diallo Traore Kone Coulibaly Toure Ndiaye Diop Cohen Levi
Mizrahi Peretz Biton Dahan Friedman Katz Azoulay Shapiro Goldberg Rosenberg Bishara
Biswas Bianco Billings Bingham Birch Moody Monroe Montgomery Morrison Mullins Mundy
Hammond Hampton Hancock Hanson Hardy Sutton Summers Sutherland Sumner Sunderland
""".split()

# (name, weight): how often coverage names them, roughly.
PUBLIC_FIGURES = [
    ("Donald Trump", 60), ("Joe Biden", 25), ("Hunter Biden", 3), ("Jill Biden", 2),
    ("Kamala Harris", 10), ("Rishi Sunak", 3), ("Akshata Murty", 1), ("Keir Starmer", 8),
    ("Boris Johnson", 3), ("Liz Truss", 1), ("Emmanuel Macron", 10), ("Olaf Scholz", 4),
    ("Friedrich Merz", 4), ("Giorgia Meloni", 5), ("Pedro Sanchez", 3),
    ("Narendra Modi", 10), ("Rahul Gandhi", 4), ("Shehbaz Sharif", 3), ("Imran Khan", 3),
    ("Xi Jinping", 10), ("Li Qiang", 2), ("Vladimir Putin", 20), ("Sergei Lavrov", 4),
    ("Volodymyr Zelensky", 15), ("Benjamin Netanyahu", 25), ("Yoav Gallant", 3),
    ("Isaac Herzog", 2), ("Yahya Sinwar", 3), ("Ismail Haniyeh", 2), ("Mahmoud Abbas", 3),
    ("Recep Tayyip Erdogan", 6), ("Ali Khamenei", 4), ("Masoud Pezeshkian", 3),
    ("Abbas Araghchi", 3), ("Mohammed bin Salman", 4), ("Elon Musk", 20), ("Jeff Bezos", 3),
    ("Mark Zuckerberg", 4), ("Sam Altman", 3), ("Bill Gates", 2), ("Tim Cook", 2),
    ("Sundar Pichai", 2), ("Satya Nadella", 2), ("Jensen Huang", 3), ("Warren Buffett", 2),
    ("Pope Francis", 5), ("King Charles", 4), ("Prince William", 3), ("Antonio Guterres", 4),
    ("Ursula von der Leyen", 5), ("Jens Stoltenberg", 2), ("Mark Rutte", 3),
    ("Javier Milei", 3), ("Luiz Inacio Lula da Silva", 4), ("Claudia Sheinbaum", 3),
    ("Justin Trudeau", 4), ("Anthony Albanese", 3), ("Shigeru Ishiba", 2),
    ("Yoon Suk Yeol", 3), ("Kim Jong Un", 3), ("Cyril Ramaphosa", 2), ("Bola Tinubu", 2),
    ("William Ruto", 2), ("Abiy Ahmed", 1), ("Taylor Swift", 3), ("Cristiano Ronaldo", 2),
    ("Lionel Messi", 2), ("Mohamed Salah", 2), ("Bernie Sanders", 2), ("Nancy Pelosi", 2),
    ("Mike Johnson", 4), ("Chuck Schumer", 3), ("JD Vance", 6), ("Marco Rubio", 5),
    ("Ron DeSantis", 2), ("Gavin Newsom", 2), ("Robert F Kennedy Jr", 3),
    ("Pete Hegseth", 3), ("Hakeem Jeffries", 2), ("Alexander Lukashenko", 2),
    ("Viktor Orban", 3), ("Donald Tusk", 3), ("Mette Frederiksen", 1), ("Kaja Kallas", 2),
    ("Christine Lagarde", 2), ("Jerome Powell", 3), ("Scott Bessent", 2),
    ("Sheikh Hasina", 2), ("Muhammad Yunus", 2), ("Anwar Ibrahim", 1),
    ("Prabowo Subianto", 2), ("Ferdinand Marcos Jr", 1), ("Lai Ching-te", 2),
    ("Naim Qassem", 1), ("Bashar al-Assad", 3), ("Ahmed al-Sharaa", 3),
    ("Abdel Fattah el-Sisi", 2), ("Mohammed bin Zayed", 1), ("Tamim bin Hamad", 1),
]  # fmt: skip

ORGANISATIONS = [
    ("Hamas", 25), ("Hezbollah", 10), ("Houthis", 5), ("Islamic Jihad", 2), ("Taliban", 3),
    ("Islamic State", 3), ("United Nations", 20), ("UNICEF", 2), ("UNESCO", 1), ("UNHCR", 1),
    ("UNRWA", 3), ("World Health Organization", 4), ("World Bank", 3),
    ("International Monetary Fund", 3), ("NATO", 10), ("European Union", 15),
    ("European Commission", 5), ("European Central Bank", 3), ("Federal Reserve", 6),
    ("Bank of England", 3), ("African Union", 1), ("ASEAN", 1), ("OPEC", 2), ("BRICS", 2),
    ("Red Cross", 2), ("Amnesty International", 2), ("Human Rights Watch", 1),
    ("Doctors Without Borders", 1), ("Pfizer", 1), ("Moderna", 1), ("AstraZeneca", 1),
    ("OpenAI", 3), ("Anthropic", 1), ("Google", 6), ("Microsoft", 5), ("Apple", 5),
    ("Amazon", 4), ("Meta", 4), ("Tesla", 5), ("SpaceX", 2), ("Nvidia", 4), ("Intel", 2),
    ("TSMC", 2), ("Samsung", 2), ("Huawei", 2), ("TikTok", 3), ("ByteDance", 1),
    ("Alibaba", 1), ("Tencent", 1), ("Netflix", 1), ("Disney", 1), ("Boeing", 3),
    ("Airbus", 1), ("Lockheed Martin", 1), ("ExxonMobil", 1), ("Shell", 1), ("BP", 1),
    ("Saudi Aramco", 1), ("Gazprom", 1), ("Volkswagen", 2), ("Toyota", 2), ("BYD", 1),
    ("Goldman Sachs", 2), ("JPMorgan Chase", 2), ("Morgan Stanley", 1), ("BlackRock", 1),
    ("HSBC", 1), ("Barclays", 1), ("Deutsche Bank", 1), ("UBS", 1), ("Reuters", 3),
    ("Associated Press", 3), ("BBC", 3), ("CNN", 2), ("Fox News", 2), ("Al Jazeera", 2),
    ("Supreme Court", 8), ("Congress", 10), ("Senate", 8), ("Pentagon", 5),
    ("White House", 12), ("State Department", 4), ("FBI", 4), ("CIA", 2), ("Kremlin", 6),
    ("Israel Defense Forces", 10), ("Wagner Group", 1), ("Labour Party", 4),
    ("Conservative Party", 3), ("Democratic Party", 4), ("Republican Party", 4),
    ("Bharatiya Janata Party", 3), ("Indian National Congress", 2), ("Likud", 1),
    ("Muslim Brotherhood", 1), ("Reform UK", 2), ("Hamas Political Bureau", 1),
]  # fmt: skip

CITIES = """
London Paris Berlin Madrid Rome Moscow Kyiv Warsaw Vienna Prague Budapest Istanbul Ankara
Tehran Baghdad Damascus Beirut Amman Cairo Riyadh Dubai Doha Jerusalem Gaza Karachi Lahore
Mumbai Delhi Kolkata Chennai Bangalore Dhaka Kathmandu Colombo Beijing Shanghai Shenzhen
Taipei Tokyo Osaka Seoul Manila Jakarta Bangkok Hanoi Sydney Melbourne Auckland Nairobi
Lagos Accra Johannesburg Durban Khartoum Kinshasa Washington Brooklyn Chicago Houston
Phoenix Philadelphia Dallas Boston Seattle Denver Miami Atlanta Toronto Montreal
Vancouver Guadalajara Bogota Lima Santiago Rosario Recife Rio
""".split()

ORG_SUFFIXES = [
    "Group",
    "Holdings",
    "Capital",
    "Foundation",
    "Institute",
    "University",
    "Bank",
    "Partners",
    "Industries",
    "Media",
    "Energy",
    "Logistics",
]
CITY_ORG_SUFFIXES = [
    "Police Department",
    "City Council",
    "University",
    "Airport",
    "Chamber of Commerce",
    "General Hospital",
    "Stock Exchange",
    "Municipal Court",
]

HEADLINE_WORDS = """
says after over amid talks war election government police killed new plan deal court
president minister attack protest market prices rise fall strike vote leaders summit
crisis report warns urges calls ban law bill tax trade tariffs growth inflation rates
storm flood fire quake rescue missing arrested charged trial verdict appeal peace
ceasefire hostages aid border migrants troops drone missile sanctions oil gas power
climate heat record team wins season final cup league coach star film music festival
health hospital vaccine outbreak study school students jobs workers union pay housing
""".split()
