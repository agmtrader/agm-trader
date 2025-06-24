'use client';
import { useEffect, useState } from 'react';
import io from 'socket.io-client';
import { Card } from "@/components/ui/card";
import LoadingComponent from '@/components/misc/LoadingComponent';
import { ColumnDefinition, DataTable } from '@/components/misc/DataTable';
import { Badge } from '@/components/ui/badge';
import { ArrowUpCircle, ArrowDownCircle, MinusCircle, DollarSign, BarChart3, TrendingUp, Briefcase, Settings, Target, Activity, Hash, Zap } from 'lucide-react';
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import TraderChart from './TraderChart';
import {
  Strategy,
  TradingDecision,
  AccountSummaryItem,
  ContractData,
  OrderData,
  PositionData,
  BacktestSnapshot,
  ExtendedTraderResponse,
  DecisionHistory
} from '@/lib/entities/trader';

import { toast } from '@/hooks/use-toast';  
import Backtest from './Backtest';

const AutoTrader = () => {
  
  const [socket, setSocket] = useState<any>(null);

  const [strategyStarted, setStrategyStarted] = useState(false);
  const [decision, setDecision] = useState<TradingDecision | null>(null);

  const [accountSummary, setAccountSummary] = useState<AccountSummaryItem[] | null>(null);
  const [strategy, setStrategy] = useState<Strategy | null>(null);
  const [backtestData, setBacktestData] = useState<BacktestSnapshot[]>([]);
  const [decisionHistory, setDecisionHistory] = useState<DecisionHistory[]>([]);

  const socketURL = 'https://167.71.94.59:3333'

  useEffect(() => {

    const newSocket = io(socketURL);
    setSocket(newSocket)

    newSocket.on('connected', (data: ExtendedTraderResponse) => {
      try {
        console.log('Connected to Trader', data);
        if (!data) throw new Error('Error connecting to Trader');
        setStrategyStarted(true);
        setDecision(data['decision'] as TradingDecision);
        setStrategy(data['strategy']);
        setAccountSummary(data['account_summary']);
        if (data['backtest']) {
          setBacktestData(data['backtest']);
          // Build decision history from backtest data
          const history = data['backtest'].map((snapshot, index) => ({
            id: index,
            decision: snapshot.decision,
            created: snapshot.current_time,
            updated: snapshot.current_time
          }));
          setDecisionHistory(history);
        }
      } catch (error) {
        toast({
          title: 'Error connecting to Trader',
          description: 'Please check your connection and try again.',
          variant: 'destructive',
        });
      }
    });

    newSocket.on('disconnected', () => {
      console.log('Disconnected from Trader');
    });

    newSocket.on('strategy_started', (data: any) => {
      console.log('Strategy started', data);
      setStrategyStarted(true);
    });

    newSocket.on('strategy_stopped', (data: any) => {
      console.log('Strategy stopped', data);
      setStrategyStarted(false);
    });

    newSocket.on('pong', (data: ExtendedTraderResponse) => {
      console.log('Pong', data);
      setDecision(data['decision'] as TradingDecision);
      setStrategy(data['strategy']);
      setAccountSummary(data['account_summary']);
      if (data['backtest']) {
        setBacktestData(data['backtest']);
        // Update decision history from backtest data
        const history = data['backtest'].map((snapshot, index) => ({
          id: index,
          decision: snapshot.decision,
          created: snapshot.current_time,
          updated: snapshot.current_time
        }));
        setDecisionHistory(history);
      }
    });

    return () => {
      newSocket.disconnect();
    };

  }, []);

  useEffect(() => {
    let interval: NodeJS.Timeout;

    if (socket && strategyStarted) {
      interval = setInterval(() => {
        socket.emit('ping');
      }, 1000);
    }

    return () => {
      if (interval) {
        clearInterval(interval);
      }
    };
  }, [socket, strategyStarted]);

  const getDecisionColor = (decision: TradingDecision | null): string => {
    switch(decision) {
      case 'LONG': return 'bg-green-100 hover:bg-green-200 text-green-800';
      case 'SHORT': return 'bg-red-100 hover:bg-red-200 text-red-800';
      case 'STAY': return 'bg-blue-100 hover:bg-blue-200 text-blue-800';
      case 'EXIT': return 'bg-yellow-100 hover:bg-yellow-200 text-yellow-800';
      default: return 'bg-gray-100 hover:bg-gray-200 text-gray-800';
    }
  };

  const getDecisionIcon = (decision: TradingDecision | null) => {
    switch(decision) {
      case 'LONG': return <ArrowUpCircle className="h-10 w-10 text-green-500" />;
      case 'SHORT': return <ArrowDownCircle className="h-10 w-10 text-red-500" />;
      case 'STAY': return <MinusCircle className="h-10 w-10 text-blue-500" />;
      case 'EXIT': return <ArrowDownCircle className="h-10 w-10 text-red-500" />;
      default: return null;
    }
  };

  if (!socket || !strategyStarted) {
    return (
      <div className='w-full h-full flex justify-center items-center'>
        <LoadingComponent className='w-full h-full'/>
      </div>
    )
  }

  const executed_order_columns = [
    {
      header: 'Symbol',
      accessorKey: 'contract.symbol',
    },
    {
      header: 'Security Type',
      accessorKey: 'contract.secType',
    },
    {
      header: 'Currency',
      accessorKey: 'contract.currency',
    },
    {
      header: 'Order Status',
      accessorKey: 'orderStatus.status',
    },
    {
      header: 'Average Fill Price',
      accessorKey: 'orderStatus.avgFillPrice',
    }
  ]

  if (strategyStarted) {
    return (
      <div className='w-full h-full p-4 '>
        <Card className="w-full h-fit p-6 bg-background">
          <div className='space-y-4'>

            <div className='rounded-lg p-4 bg-background'>
              <div className='flex justify-between items-center'>
                <div className='flex items-center'>
                  <BarChart3 className="h-8 w-8 mr-3 text-primary" />
                  <div>
                    <h1 className='text-2xl font-bold text-foreground'>AGM Trader Dashboard</h1>
                  </div>
                </div>
                <div>
                  <Badge className={`text-lg py-2 px-4 ${getDecisionColor(decision)}`}>
                    {getDecisionIcon(decision)}
                    <span className="ml-2 font-bold">{decision || 'Initializing...'}</span>
                  </Badge>
                </div>
              </div>
            </div>

            <Tabs defaultValue="overview" className="w-full">
              <TabsList className="grid w-full grid-cols-3 mb-4">
                <TabsTrigger value="overview">Overview</TabsTrigger>
                <TabsTrigger value="chart">Chart Analysis</TabsTrigger>
                <TabsTrigger value="backtest">Backtest</TabsTrigger>
              </TabsList>

              <TabsContent value="overview" className="mt-0">
                <div className='grid grid-cols-12 gap-4'>
                  <div className='col-span-12 md:col-span-4'>
                    <div className="h-full rounded-lg p-4 bg-background">
                      <div className="flex items-center mb-4">
                        <Briefcase className="h-5 w-5 mr-2 text-primary" />
                        <h2 className="text-lg font-semibold text-foreground">Strategy Details</h2>
                      </div>
                      {strategy && strategy.params ? (
                        <div className='gap-4 flex flex-col'>
                          {/* Strategy Name */}
                          <div className='flex w-full flex-col p-4 bg-muted rounded-lg'>
                            <div className='flex items-center gap-2 text-muted-foreground'>
                              <Settings className="h-4 w-4" />
                              <span className='text-sm'>Strategy Name</span>
                            </div>
                            <span className='font-bold text-lg text-primary'>
                              {strategy.name || 'Ichimoku Base'}
                            </span>
                          </div>

                          {/* Contracts */}
                          <div className='space-y-3'>
                            <div className='flex items-center gap-2 text-muted-foreground'>
                              <Activity className="h-4 w-4" />
                              <span className='text-sm font-medium'>Trading Contracts</span>
                            </div>
                            <div className='grid grid-cols-2 gap-3'>
                              {strategy.params.contracts.map((contractData: ContractData) => (
                                <div key={contractData.symbol} className='flex w-full flex-col p-4 bg-muted rounded-lg'>
                                  <div className='flex items-center gap-2 text-muted-foreground'>
                                    <Target className="h-4 w-4" />
                                    <span className='text-sm'>Contract</span>
                                  </div>
                                  <span className='font-bold text-lg text-foreground'>
                                    {contractData.symbol}
                                  </span>
                                </div>
                              ))}
                            </div>
                          </div>

                          {/* Strategy Parameters */}
                          <div className='space-y-3'>
                            <div className='flex items-center gap-2 text-muted-foreground'>
                              <BarChart3 className="h-4 w-4" />
                              <span className='text-sm font-medium'>Strategy Parameters</span>
                            </div>
                            <div className='grid grid-cols-2 gap-4'>
                              <div className='flex w-full flex-col p-4 bg-muted rounded-lg'>
                                <div className='flex items-center gap-2 text-muted-foreground'>
                                  <TrendingUp className="h-4 w-4" />
                                  <span className='text-sm'>Tenkan</span>
                                </div>
                                <span className='font-bold text-lg text-foreground'>
                                  {strategy.params.tenkan}
                                </span>
                              </div>
                              <div className='flex w-full flex-col p-4 bg-muted rounded-lg'>
                                <div className='flex items-center gap-2 text-muted-foreground'>
                                  <Activity className="h-4 w-4" />
                                  <span className='text-sm'>Kijun</span>
                                </div>
                                <span className='font-bold text-lg text-foreground'>
                                  {strategy.params.kijun}
                                </span>
                              </div>
                              <div className='flex w-full flex-col p-4 bg-muted rounded-lg'>
                                <div className='flex items-center gap-2 text-muted-foreground'>
                                  <Zap className="h-4 w-4" />
                                  <span className='text-sm'>PSAR MES</span>
                                </div>
                                <span className='font-bold text-lg text-foreground'>
                                  {strategy.params.psar_mes.length > 0 ? strategy.params.psar_mes[strategy.params.psar_mes.length - 1].toFixed(2) : 'N/A'}
                                </span>
                              </div>
                              <div className='flex w-full flex-col p-4 bg-muted rounded-lg'>
                                <div className='flex items-center gap-2 text-muted-foreground'>
                                  <Zap className="h-4 w-4" />
                                  <span className='text-sm'>PSAR MYM</span>
                                </div>
                                <span className='font-bold text-lg text-foreground'>
                                  {strategy.params.psar_mym.length > 0 ? strategy.params.psar_mym[strategy.params.psar_mym.length - 1].toFixed(2) : 'N/A'}
                                </span>
                              </div>
                              <div className='flex w-full flex-col p-4 bg-muted rounded-lg col-span-2'>
                                <div className='flex items-center gap-2 text-muted-foreground'>
                                  <Hash className="h-4 w-4" />
                                  <span className='text-sm'>Number of Contracts</span>
                                </div>
                                <span className='font-bold text-lg text-foreground'>
                                  {strategy.params.number_of_contracts}
                                </span>
                              </div>
                            </div>
                          </div>
                        </div>
                      ) : (
                        <LoadingComponent className='w-full h-full'/>
                      )}
                    </div>
                  </div>

                  {/* Market Data */}
                  <div className='col-span-12 md:col-span-4'>
                    <div className="h-full w-full flex flex-col rounded-lg p-4 bg-background">
                      <div className="flex items-center mb-4">
                        <TrendingUp className="h-5 w-5 mr-2 text-primary" />
                        <h2 className="text-lg font-semibold text-foreground">Last Market Data</h2>
                      </div>
                      {strategy && strategy.params && strategy.params.contracts.length > 0 ? (
                        <div className='w-full flex flex-col gap-4'>
                          {strategy.params.contracts.map((contractData: ContractData) => (
                            <div key={contractData.symbol} className='w-full'>
                              <div className='flex items-center gap-2 mb-3'>
                                <Activity className="h-4 w-4 text-primary" />
                                <span className='text-sm font-semibold text-foreground'>{contractData.symbol}</span>
                                <span className='text-xs text-muted-foreground'>
                                  ({contractData.data_points} data points)
                                </span>
                              </div>
                              <div className='grid grid-cols-2 gap-4'>
                                <div className='flex w-full flex-col p-4 bg-muted rounded-lg'>
                                  <div className='flex items-center gap-2 text-muted-foreground'>
                                    <ArrowUpCircle className="h-4 w-4" />
                                    <span className='text-sm'>Open</span>
                                  </div>
                                  <span className='font-bold text-lg text-foreground'>
                                    {contractData.has_data && contractData.data.length > 0 
                                      ? contractData.data[contractData.data.length - 1].open.toFixed(2) 
                                      : 'No data'
                                    }
                                  </span>
                                </div>
                                <div className='flex w-full flex-col p-4 bg-muted rounded-lg'>
                                  <div className='flex items-center gap-2 text-muted-foreground'>
                                    <TrendingUp className="h-4 w-4" />
                                    <span className='text-sm'>High</span>
                                  </div>
                                  <span className='font-bold text-lg text-green-500'>
                                    {contractData.has_data && contractData.data.length > 0 
                                      ? contractData.data[contractData.data.length - 1].high.toFixed(2) 
                                      : 'No data'
                                    }
                                  </span>
                                </div>
                                <div className='flex w-full flex-col p-4 bg-muted rounded-lg'>
                                  <div className='flex items-center gap-2 text-muted-foreground'>
                                    <ArrowDownCircle className="h-4 w-4" />
                                    <span className='text-sm'>Low</span>
                                  </div>
                                  <span className='font-bold text-lg text-red-500'>
                                    {contractData.has_data && contractData.data.length > 0 
                                      ? contractData.data[contractData.data.length - 1].low.toFixed(2) 
                                      : 'No data'
                                    }
                                  </span>
                                </div>
                                <div className='flex w-full flex-col p-4 bg-muted rounded-lg'>
                                  <div className='flex items-center gap-2 text-muted-foreground'>
                                    <MinusCircle className="h-4 w-4" />
                                    <span className='text-sm'>Close</span>
                                  </div>
                                  <span className='font-bold text-lg text-foreground'>
                                    {contractData.has_data && contractData.data.length > 0 
                                      ? contractData.data[contractData.data.length - 1].close.toFixed(2) 
                                      : 'No data'
                                    }
                                  </span>
                                </div>
                              </div>
                              {contractData.has_data && contractData.data.length > 0 && (
                                <div className='mt-3 flex items-center gap-4 text-xs text-muted-foreground'>
                                  <span>Volume: {contractData.data[contractData.data.length - 1].volume || 'N/A'}</span>
                                  <span>Date: {contractData.data[contractData.data.length - 1].date}</span>
                                </div>
                              )}
                            </div>
                          ))}
                        </div>
                      ) : (
                        <LoadingComponent className='w-full h-full'/>
                      )}
                    </div>
                  </div>

                  {/* Account Summary */}
                  <div className='col-span-12 md:col-span-4'>
                    <div className='flex flex-col h-full rounded-lg p-4 bg-background'>
                      <div className="flex items-center mb-4">
                        <DollarSign className="h-5 w-5 mr-2 text-primary" />
                        <h2 className="text-lg font-semibold text-foreground">Account Summary</h2>
                      </div>
                      {accountSummary ? (
                        <div className='grid grid-cols-2 md:grid-cols-2 gap-4'>
                          {[
                            { tag: 'BuyingPower', icon: <DollarSign className="h-4 w-4" /> },
                            { tag: 'NetLiquidation', icon: <DollarSign className="h-4 w-4" /> },
                            { tag: 'TotalCashValue', icon: <DollarSign className="h-4 w-4" /> },
                            { tag: 'AvailableFunds', icon: <DollarSign className="h-4 w-4" /> },
                            { tag: 'UnrealizedPnL', icon: <TrendingUp className="h-4 w-4" /> },
                            { tag: 'RealizedPnL', icon: <TrendingUp className="h-4 w-4" /> },
                          ].map((item) => {
                            const summary = accountSummary.find((s: AccountSummaryItem) => s.tag === item.tag);
                            return summary ? (
                              <div key={item.tag} className='flex h-20 w-full flex-col p-4 bg-muted rounded-lg'>
                                <div className='flex items-center gap-2 text-muted-foreground'>
                                  {item.icon}
                                  <span className='text-sm'>{item.tag}</span>
                                </div>
                                <span className={`font-bold text-lg ${
                                  item.tag.includes('PnL') 
                                    ? parseFloat(summary.value) > 0 
                                      ? 'text-green-500' 
                                      : parseFloat(summary.value) < 0 
                                        ? 'text-red-500' 
                                        : 'text-foreground'
                                    : 'text-foreground'
                                }`}>
                                  {summary.currency ? `${summary.value} ${summary.currency}` : summary.value}
                                </span>
                              </div>
                            ) : null;
                          })}
                        </div>
                      ) : (
                        <LoadingComponent className='w-full h-full'/>
                      )}
                    </div>
                  </div>

                  {/* Open Orders */}
                  <div className='col-span-12'>
                    <div className='rounded-lg p-4 bg-background'>
                      <div className="flex items-center mb-4">
                        <Briefcase className="h-5 w-5 mr-2 text-primary" />
                        <h2 className="text-lg font-semibold text-foreground">Open Orders</h2>
                      </div>
                      {strategy && strategy.params && strategy.params.open_orders ? (
                        <div className="overflow-x-auto w-full">
                          <DataTable<OrderData> data={strategy.params.open_orders || []} />
                        </div>
                      ) : (
                        <LoadingComponent className='w-full h-full'/>
                      )}
                    </div>
                  </div>

                  {/* Positions */}
                  <div className='col-span-12'>
                    <div className='rounded-lg p-4 bg-background'>
                      <div className="flex items-center mb-4">
                        <TrendingUp className="h-5 w-5 mr-2 text-primary" />
                        <h2 className="text-lg font-semibold text-foreground">Positions</h2>
                      </div>
                      {strategy && strategy.params && strategy.params.positions ? (
                        <div className="overflow-x-auto w-full">
                          <DataTable<PositionData> data={strategy.params.positions || []} />
                        </div>
                      ) : (
                        <LoadingComponent className='w-full h-full'/>
                      )}
                    </div>
                  </div>

                  {/* Recently Executed Orders */}
                  <div className='col-span-12'>
                    <div className="rounded-lg p-4 bg-background">
                      <div className="flex items-center mb-4">
                        <ArrowDownCircle className="h-5 w-5 mr-2 text-primary" />
                        <h2 className="text-lg font-semibold text-foreground">Recently Executed Orders</h2>
                      </div>
                      {strategy && strategy.params && strategy.params.executed_orders ? (
                        <div className="overflow-x-auto w-full">
                          <DataTable<OrderData>
                            columns={executed_order_columns as ColumnDefinition<OrderData>[]}
                            data={strategy.params.executed_orders || []} 
                            enablePagination 
                            pageSize={5}
                          />
                        </div>
                      ) : (
                        <LoadingComponent className='w-full h-full'/>
                      )}
                    </div>
                  </div>
                </div>
              </TabsContent>

              <TabsContent value="chart" className="mt-0">
                {strategy && strategy.params && strategy.params.contracts ? (
                  <div className="rounded-lg p-4 bg-background space-y-6">
                    <h2 className="text-lg font-semibold text-foreground">Historical Data Analysis</h2>
                    {strategy.params.contracts.map((contract, index) => {
                      const indicator = index === 0 ? strategy.params.psar_mes || [] : strategy.params.psar_mym || [];
                      return (
                        <TraderChart
                          key={contract.symbol}
                          contract={contract}
                          indicator={indicator}
                          decisions={decisionHistory}
                          title={`${contract.symbol} Trading Chart`}
                        />
                      );
                    })}
                  </div>
                ) : (
                  <LoadingComponent className='w-full h-[600px]'/>
                )}
              </TabsContent>

              <TabsContent value="backtest" className="mt-0">
                {strategy && strategy.params && strategy.params.contracts ? (
                  <Backtest backtestData={backtestData} strategy={strategy} decisionHistory={decisionHistory} />
                ) : (
                  <LoadingComponent className='w-full h-[600px]'/>
                )}
              </TabsContent>
            </Tabs>
          </div>
        </Card>
      </div>
    )
  }

  return null
}

export default AutoTrader