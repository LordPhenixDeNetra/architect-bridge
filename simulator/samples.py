"""Messages ARCHITECT construits a partir des exemples du manuel ASI (section 4)."""

H = "H|\\^&|||ARCHITECT^1.00^123456789^H1P1O1R1C1Q1L1|||||||P|1|19990715081500\r"

BHCG = (
    H
    + "P|1|||PIDSID13|PATIENT^IM^A||19320122|F\r"
    "O|1|SID13|SID13^A123^5|^^^0021^B-hCG^UNDILUTED^P|R||||||||||||||||||||F\r"
    "R|1|^^^0021^B-hCG^UNDILUTED^P^47331M100^00788^^F|<1.20|mIU/mL|0.35 TO 4.94|<||F||||19990715081030|I20100\r"
    "R|2|^^^0021^B-hCG^UNDILUTED^P^47331M100^00788^^I|NEGATIVE|||||F||||19990715081030|I20100\r"
    "R|3|^^^0021^B-hCG^UNDILUTED^P^47331M100^00788^^P|9245|RLU||||F||||19990715081030|I20100\r"
    "C|1|I|Example Result Comment|G\r"
    "L|1\r"
)

CONTROL = (
    H
    + "P|1\r"
    "O|1|TSHBIORAD 2|TSHBIORAD 2^A123^2|^^^0241^TSH^UNDILUTED^P|R||||||Q||||||||||||||F\r"
    "R|1|^^^0241^TSH^UNDILUTED^P^0607M200^01824^40080^F|4.6011|mIU/mL|4.292500 TO 5.397300|||F||ECB^RY||19990715081030|I20100\r"
    "L|1\r"
)

EXCEPTION = (
    H
    + "P|1\r"
    "O|1|SID9|SID9^A1^1|^^^0241^TSH^UNDILUTED^P|R||||||||||||||||||||X\r"
    "C|1|I|Sample short|I\r"
    "L|1\r"
)
