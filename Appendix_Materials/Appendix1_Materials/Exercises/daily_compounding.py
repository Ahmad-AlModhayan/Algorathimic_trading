# Function to calculate the return of trading for specific time.
# Future Value
# Present Value

# TVM (Time Value of money)

def Calculator():
    
    PV = int (input('Please enter your bais amount: ')) # Present Value
    IR = float (input('Please enter Intrest rate: ')) / 100 # Intrest Rate
    DAYS = int (input('Please enter how many days to calculate: ')) # Days
    
    FV : float = PV * (1 + IR)**DAYS
    
    print(FV)



Calculator()
